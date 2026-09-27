"""ConfigurationFileManager-specific tests.

Protocol-level behavior shared with other manager implementations (collection
visibility, pagination, capability-driven `CapabilityNotSupported` raising, user
lookups, authentication, resource-editor/viewer listing) lives in
`tests/test_manager_contract.py` instead, parametrized across all manager backends.
This file only covers what's genuinely specific to this manager: TOML parsing/
type-coercion, and its file-existence-based health check.
"""

import types
from pathlib import Path
from typing import Any

import pytest
import shapely
from starlette_admin import RequestAction

from potto import config
from potto.constants import CollectionType, ProvidedDataType
from potto.exceptions import CapabilityNotSupported
from potto.managers.configurationfile import manager as configurationfile_manager
from potto.managers.configurationfile import parsing
from potto.schemas.auth import PottoUser, UserCreateFromOidc


class _FakeAdminRequestState:
    def __init__(self, manager: configurationfile_manager.ConfigurationFileManager):
        self.SETTINGS = _FakeAdminSettings(manager)
        self.ROUTE_NAME = "admin"


class _FakeAdminSettings:
    """Just enough of PottoSettings' interface for the admin view under test.

    The admin view only ever reaches settings via ``request.app.state.SETTINGS``, so
    there's no need to construct a fully-wired ``PottoSettings`` pointing at this
    manager - this stands in for it, delegating every manager getter to the same
    ``ConfigurationFileManager`` instance (which implements all three protocols).
    """

    def __init__(self, manager: configurationfile_manager.ConfigurationFileManager):
        self._manager = manager

    def get_collection_manager(self):
        return self._manager

    def get_server_metadata_manager(self):
        return self._manager

    def get_user_account_manager(self):
        return self._manager

    def get_process_manager(self):
        return self._manager

    def get_authorization_backend(self):
        return self._manager.authorization_backend


class _FakeAdminRequestApp:
    def __init__(self, manager: configurationfile_manager.ConfigurationFileManager):
        self.state = _FakeAdminRequestState(manager)


class _FakeAdminRequest:
    def __init__(
        self,
        manager: configurationfile_manager.ConfigurationFileManager,
        user: PottoUser,
        action: RequestAction = RequestAction.LIST,
    ):
        self.app = _FakeAdminRequestApp(manager)
        self.user = user
        self.state = types.SimpleNamespace(action=action)
        self.path_params: dict[str, Any] = {}

    def url_for(self, *args: Any, **kwargs: Any) -> str:
        return "/fake"


SAMPLE_CONFIG_FILE = (
    Path(__file__).parent / "data" / "configurationfile" / "sample_config.toml"
)


@pytest.fixture
def settings() -> config.PottoSettings:
    return config.PottoSettings()


@pytest.fixture
def manager(settings) -> configurationfile_manager.ConfigurationFileManager:
    return configurationfile_manager.get_configuration_file_manager(
        {"config_file": SAMPLE_CONFIG_FILE}, settings
    )


@pytest.fixture
def admin_user(manager) -> PottoUser:
    return manager.user_accounts["admin-1"]


class TestParsing:
    def test_collections_have_correctly_typed_fields(self, manager):
        geo_collection = manager.collections["geo-collection"]
        assert geo_collection.type_ is CollectionType.FEATURE_COLLECTION
        assert isinstance(geo_collection.owner, PottoUser)
        assert geo_collection.owner.id == "admin-1"
        assert isinstance(geo_collection.spatial_extent, shapely.Geometry)
        assert ProvidedDataType.FEATURE in geo_collection.providers
        assert geo_collection.providers[ProvidedDataType.FEATURE].provider_name == (
            "collection-config"
        )

    def test_server_metadata_has_correctly_typed_nested_fields(self, manager):
        server_metadata = manager.server_metadata
        assert server_metadata.license is not None
        assert server_metadata.license.name == "CC-BY-4.0"
        assert server_metadata.data_provider is not None
        assert server_metadata.data_provider.name == "Geobeyond"
        assert server_metadata.point_of_contact is not None
        assert server_metadata.point_of_contact.name == "Jane Doe"

    def test_unknown_owner_id_raises(self, manager):
        with pytest.raises(ValueError, match="unknown owner_id"):
            parsing.parse_collections(
                [{"identifier": "broken", "owner_id": "does-not-exist"}],
                manager.user_accounts,
            )

    def test_processes_have_correctly_typed_fields(self, manager):
        public_process = manager.processes["public-process"]
        assert isinstance(public_process.owner, PottoUser)
        assert public_process.owner.id == "user-1"
        assert public_process.execution_unit.type_ == "other"
        assert len(public_process.inputs) == 1
        assert public_process.inputs[0].title == "Input area"
        assert len(public_process.outputs) == 1
        assert public_process.deployment_status.value == "deployed"

    def test_process_deployment_status_defaults_to_failed(self, manager):
        # private-process has no `[process.deployment_status]` table in the sample
        # config, mirroring PostgisManager's Process.to_potto() fallback.
        private_process = manager.processes["private-process"]
        assert private_process.deployment_status.value == "failed"

    def test_process_unknown_owner_id_raises(self, manager):
        with pytest.raises(ValueError, match="unknown owner_id"):
            parsing.parse_processes(
                [{"identifier": "broken", "owner_id": "does-not-exist"}],
                manager.user_accounts,
            )


class TestCollections:
    @pytest.mark.asyncio
    async def test_get_collection_admin_view_is_read_only(self, manager):
        view = await manager.get_collection_admin_view()
        assert view is not None
        assert view.pk_attr == "identifier"
        assert view.can_create(None) is False
        assert view.can_edit(None) is False
        assert view.can_delete(None) is False

    @pytest.mark.asyncio
    async def test_collection_admin_view_find_all(self, manager, admin_user):
        view = await manager.get_collection_admin_view()
        request = _FakeAdminRequest(manager, admin_user)
        results = await view.find_all(request)
        assert {c.identifier for c in results} == set(manager.collections.keys())

    @pytest.mark.asyncio
    async def test_collection_admin_view_find_by_pk(self, manager, admin_user):
        view = await manager.get_collection_admin_view()
        request = _FakeAdminRequest(manager, admin_user)
        collection = await view.find_by_pk(request, "public-collection")
        assert collection is not None
        assert collection.identifier == "public-collection"
        assert collection.editors == []
        assert collection.viewers == []

    @pytest.mark.asyncio
    async def test_collection_admin_view_count(self, manager, admin_user):
        view = await manager.get_collection_admin_view()
        request = _FakeAdminRequest(manager, admin_user)
        assert await view.count(request) == len(manager.collections)


class TestProcesses:
    @pytest.mark.asyncio
    async def test_get_process_admin_view_is_read_only(self, manager):
        view = await manager.get_process_admin_view()
        assert view is not None
        assert view.pk_attr == "identifier"
        assert view.can_create(None) is False
        assert view.can_edit(None) is False
        assert view.can_delete(None) is False

    @pytest.mark.asyncio
    async def test_process_admin_view_find_all(self, manager, admin_user):
        view = await manager.get_process_admin_view()
        request = _FakeAdminRequest(manager, admin_user)
        results = await view.find_all(request)
        assert {p.identifier for p in results} == set(manager.processes.keys())

    @pytest.mark.asyncio
    async def test_process_admin_view_find_by_pk(self, manager, admin_user):
        view = await manager.get_process_admin_view()
        request = _FakeAdminRequest(manager, admin_user)
        process = await view.find_by_pk(request, "public-process")
        assert process is not None
        assert process.identifier == "public-process"
        assert process.editors == []
        assert process.viewers == []

    @pytest.mark.asyncio
    async def test_process_admin_view_count(self, manager, admin_user):
        view = await manager.get_process_admin_view()
        request = _FakeAdminRequest(manager, admin_user)
        assert await view.count(request) == len(manager.processes)

    @pytest.mark.asyncio
    async def test_process_admin_view_serialize_shows_inputs_outputs_and_execution_unit(
        self, manager, admin_user
    ):
        view = await manager.get_process_admin_view()
        request = _FakeAdminRequest(manager, admin_user, action=RequestAction.DETAIL)
        process = await view.find_by_pk(request, "public-process")
        result = await view.serialize(process, request, RequestAction.DETAIL)
        assert result["inputs"] == [
            {
                "title": "Input area",
                "schema": {"type": "string"},
                "min_occurs": 1,
                "max_occurs": 1,
                "description": None,
                "keywords": None,
            }
        ]
        assert result["outputs"] == [
            {
                "title": "Output result",
                "schema": {"type": "string"},
                "min_occurs": 1,
                "max_occurs": 1,
                "description": None,
                "keywords": None,
                "data_classes": None,
                "data_access_apis": None,
            }
        ]
        assert result["execution_unit"] == {
            "type_": "other",
            "definition": {"echo": "hello"},
        }
        assert result["deployment_status"] == {"value": "deployed", "detail": None}


class TestServerMetadata:
    @pytest.mark.asyncio
    async def test_get_server_metadata_admin_view_is_read_only(self, manager):
        view = await manager.get_server_metadata_admin_view()
        assert view is not None
        assert view.pk_attr == "id"
        assert view.can_create(None) is False
        assert view.can_edit(None) is False
        assert view.can_delete(None) is False

    @pytest.mark.asyncio
    async def test_server_metadata_admin_view_find_all_and_find_by_pk(
        self, manager, admin_user
    ):
        view = await manager.get_server_metadata_admin_view()
        request = _FakeAdminRequest(manager, admin_user)
        results = await view.find_all(request)
        assert results == [manager.server_metadata]

        found = await view.find_by_pk(request, "anything")
        assert found == manager.server_metadata

    @pytest.mark.asyncio
    async def test_server_metadata_admin_view_count(self, manager, admin_user):
        view = await manager.get_server_metadata_admin_view()
        request = _FakeAdminRequest(manager, admin_user)
        assert await view.count(request) == 1


class TestUserAccounts:
    @pytest.mark.asyncio
    async def test_authenticate_no_local_password(self, manager):
        # bob (user-2) has no `hashed_password` set in the sample config - a manager
        # backing an OIDC-only deployment. PostgisManager can't produce this
        # scenario through its protocol (UserCreate.password is required), so it
        # stays configurationfile-specific.
        assert await manager.authenticate("bob", "whatever") is None

    @pytest.mark.asyncio
    async def test_provision_oidc_user_raises(self, manager):
        # Not capability-gated (UserAccountManagerCapabilities has no corresponding
        # flag), so it can't be part of the shared, capability-branched contract test.
        with pytest.raises(CapabilityNotSupported):
            await manager.provision_oidc_user(
                UserCreateFromOidc(id="oidc-1", username="oidcuser")
            )

    @pytest.mark.asyncio
    async def test_get_user_account_admin_view_is_read_only(self, manager):
        view = await manager.get_user_account_admin_view()
        assert view is not None
        assert view.pk_attr == "id"
        assert view.can_create(None) is False
        assert view.can_edit(None) is False
        assert view.can_delete(None) is False

    @pytest.mark.asyncio
    async def test_user_account_admin_view_find_all(self, manager, admin_user):
        view = await manager.get_user_account_admin_view()
        request = _FakeAdminRequest(manager, admin_user)
        results = await view.find_all(request)
        assert {u.id for u in results} == set(manager.user_accounts.keys())

    @pytest.mark.asyncio
    async def test_user_account_admin_view_find_all_filters_by_username(
        self, manager, admin_user
    ):
        view = await manager.get_user_account_admin_view()
        request = _FakeAdminRequest(manager, admin_user)
        results = await view.find_all(request, where="ali")
        assert {u.username for u in results} == {"alice"}

    @pytest.mark.asyncio
    async def test_user_account_admin_view_find_by_pk(self, manager, admin_user):
        view = await manager.get_user_account_admin_view()
        request = _FakeAdminRequest(manager, admin_user)
        found = await view.find_by_pk(request, "admin-1")
        assert found is not None
        assert found.username == "admin"

    @pytest.mark.asyncio
    async def test_user_account_admin_view_count(self, manager, admin_user):
        view = await manager.get_user_account_admin_view()
        request = _FakeAdminRequest(manager, admin_user)
        assert await view.count(request) == len(manager.user_accounts)


class TestCommon:
    @pytest.mark.asyncio
    async def test_check_health_missing_file(self, settings, tmp_path):
        config_file = tmp_path / "will-be-deleted.toml"
        config_file.write_text('[server_metadata]\ntitle = "Minimal"\n')
        instance_manager = configurationfile_manager.ConfigurationFileManager(
            configurationfile_manager.ConfigurationFileManagerConfiguration(
                config_file=config_file
            ),
            settings.get_authorization_backend(),
        )
        config_file.unlink()
        assert await instance_manager.check_health() == "error"

    def test_potto_cli_group(self, manager):
        assert manager.potto_cli_group == "configuration-file-manager"
