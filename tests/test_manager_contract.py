"""Manager-protocol contract tests.

Every test here takes the `contract_harness` fixture (defined in
`tests/manager_contract.py`) and is written purely in terms of it - the same
assertions run, unmodified, against both `PostgisManager` and
`ConfigurationFileManager`, since both are expected to conform to the same
`CollectionManagerProtocol`/`ServerMetadataProtocol`/`UserAccountProtocol` contract.

Backend-specific behavior (TOML type-coercion, postgis DB-constraint tests, HTTP/
serialization concerns) stays in its own test file - see
`tests/test_manager_configurationfile.py` and `tests/test_commands_collections.py`.
"""

import pytest
import shapely
from pydantic import SecretStr

from potto.constants import CollectionType
from potto.exceptions import (
    CapabilityNotSupported,
    PottoCannotDeleteUserException,
    PottoCannotEditUserException,
    PottoCannotViewUserException,
)
from potto.schemas.auth import (
    UserCreate,
    UserFilter,
    UserUpdate,
)
from potto.schemas.collections import (
    CollectionCreate,
    CollectionFilter,
    CollectionUpdate,
)
from potto.schemas.metadata import ServerMetadataUpdate

# Matches manager_contract.py's SPATIAL_EXTENT_WKT: x in [-10, 5], y in [40, 50].
_POINT_INSIDE_SPATIAL_EXTENT = shapely.Point(0, 45)


class TestCollectionVisibility:
    @pytest.mark.asyncio
    async def test_public_collection_visible_to_anonymous(self, contract_harness):
        result = await contract_harness.manager.get_collection(
            contract_harness.public_collection.identifier, None
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_private_collection_hidden_from_anonymous(self, contract_harness):
        result = await contract_harness.manager.get_collection(
            contract_harness.private_collection.identifier, None
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_private_collection_hidden_from_unrelated_user(
        self, contract_harness
    ):
        result = await contract_harness.manager.get_collection(
            contract_harness.private_collection.identifier, contract_harness.other_user
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_private_collection_visible_to_owner(self, contract_harness):
        result = await contract_harness.manager.get_collection(
            contract_harness.private_collection.identifier, contract_harness.owner_user
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_private_collection_visible_to_viewer(self, contract_harness):
        result = await contract_harness.manager.get_collection(
            contract_harness.private_collection.identifier, contract_harness.viewer_user
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_private_collection_visible_to_editor(self, contract_harness):
        result = await contract_harness.manager.get_collection(
            contract_harness.private_collection.identifier, contract_harness.editor_user
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_private_collection_visible_to_admin(self, contract_harness):
        result = await contract_harness.manager.get_collection(
            contract_harness.private_collection.identifier, contract_harness.admin_user
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_get_collection_missing_returns_none(self, contract_harness):
        result = await contract_harness.manager.get_collection(
            "does-not-exist-xyz", contract_harness.admin_user
        )
        assert result is None


class TestCollectionListing:
    @pytest.mark.asyncio
    async def test_anonymous_sees_only_public_collections(self, contract_harness):
        results, _ = await contract_harness.manager.paginated_list_collections(None)
        identifiers = {c.identifier for c in results}
        assert contract_harness.public_collection.identifier in identifiers
        assert contract_harness.spatial_collection.identifier in identifiers
        assert contract_harness.private_collection.identifier not in identifiers

    @pytest.mark.asyncio
    async def test_admin_sees_private_collection(self, contract_harness):
        results, _ = await contract_harness.manager.paginated_list_collections(
            contract_harness.admin_user
        )
        identifiers = {c.identifier for c in results}
        assert contract_harness.private_collection.identifier in identifiers

    @pytest.mark.asyncio
    async def test_identifier_filter(self, contract_harness):
        results, _ = await contract_harness.manager.paginated_list_collections(
            contract_harness.admin_user,
            filter_=CollectionFilter(
                identifiers=[contract_harness.public_collection.identifier]
            ),
        )
        identifiers = {c.identifier for c in results}
        assert identifiers == {contract_harness.public_collection.identifier}

    @pytest.mark.asyncio
    async def test_type_filter_excludes_unmatched_type(self, contract_harness):
        results, _ = await contract_harness.manager.paginated_list_collections(
            contract_harness.admin_user,
            filter_=CollectionFilter(type_=CollectionType.COVERAGE),
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_type_filter_includes_matched_type(self, contract_harness):
        results, _ = await contract_harness.manager.paginated_list_collections(
            contract_harness.admin_user,
            filter_=CollectionFilter(type_=CollectionType.FEATURE_COLLECTION),
        )
        identifiers = {c.identifier for c in results}
        assert contract_harness.public_collection.identifier in identifiers

    @pytest.mark.asyncio
    async def test_spatial_intersect_filter(self, contract_harness):
        # A collection with no spatial_extent is treated as unbounded and always
        # matches (public_collection/private_collection have none); spatial_collection
        # has an extent that intersects the test point; distant_collection has one
        # that doesn't, so it's the only one excluded.
        results, _ = await contract_harness.manager.paginated_list_collections(
            contract_harness.admin_user,
            filter_=CollectionFilter(spatial_intersect=_POINT_INSIDE_SPATIAL_EXTENT),
        )
        identifiers = {c.identifier for c in results}
        assert contract_harness.spatial_collection.identifier in identifiers
        assert contract_harness.public_collection.identifier in identifiers
        assert contract_harness.distant_collection.identifier not in identifiers

    @pytest.mark.asyncio
    async def test_pagination_consistent_with_total(self, contract_harness):
        manager = contract_harness.manager
        admin = contract_harness.admin_user
        all_results, total = await manager.paginated_list_collections(
            admin, page=1, page_size=1000, include_total=True
        )
        assert total == len(all_results)
        assert total >= 3
        page_1, _ = await manager.paginated_list_collections(admin, page=1, page_size=2)
        page_2, _ = await manager.paginated_list_collections(admin, page=2, page_size=2)
        combined_identifiers = [c.identifier for c in page_1 + page_2]
        expected_identifiers = [
            c.identifier for c in all_results[: len(page_1) + len(page_2)]
        ]
        assert combined_identifiers == expected_identifiers


class TestCollectionMutationCapabilities:
    @pytest.mark.asyncio
    async def test_create_collection(self, contract_harness):
        manager = contract_harness.manager
        capabilities = await manager.get_collection_capabilities()
        to_create = CollectionCreate(
            resource_identifier="contract-created-collection",
            owner_id=contract_harness.owner_user.id,
            collection_type=CollectionType.FEATURE_COLLECTION,
            title="Newly created collection",
        )
        if capabilities.supports_creation:
            created = await manager.create_collection(
                to_create, contract_harness.owner_user
            )
            assert created.identifier == "contract-created-collection"
            fetched = await manager.get_collection(
                "contract-created-collection", contract_harness.owner_user
            )
            assert fetched is not None
        else:
            with pytest.raises(CapabilityNotSupported):
                await manager.create_collection(to_create, contract_harness.owner_user)

    @pytest.mark.asyncio
    async def test_update_collection(self, contract_harness):
        manager = contract_harness.manager
        capabilities = await manager.get_collection_capabilities()
        to_update = CollectionUpdate(title="Updated title")
        if capabilities.supports_modification:
            updated = await manager.update_collection(
                contract_harness.private_collection,
                to_update,
                contract_harness.owner_user,
            )
            assert updated.title == "Updated title"
        else:
            with pytest.raises(CapabilityNotSupported):
                await manager.update_collection(
                    contract_harness.private_collection,
                    to_update,
                    contract_harness.owner_user,
                )

    @pytest.mark.asyncio
    async def test_delete_collection(self, contract_harness):
        manager = contract_harness.manager
        capabilities = await manager.get_collection_capabilities()
        identifier = contract_harness.public_collection.identifier
        if capabilities.supports_deletion:
            await manager.delete_collection(identifier, contract_harness.owner_user)
            assert (
                await manager.get_collection(identifier, contract_harness.admin_user)
                is None
            )
        else:
            with pytest.raises(CapabilityNotSupported):
                await manager.delete_collection(identifier, contract_harness.owner_user)

    @pytest.mark.asyncio
    async def test_grant_and_revoke_collection_access(self, contract_harness):
        manager = contract_harness.manager
        capabilities = await manager.get_collection_capabilities()
        if capabilities.supports_granting_access:
            await manager.grant_collection_access(
                granting_user=contract_harness.owner_user,
                target_user_id=contract_harness.other_user.id,
                collection=contract_harness.private_collection,
                role="viewer",
            )
            # Authorization checks read `user.scopes` off the object it's given, not
            # a fresh DB row - re-fetch to see the effect of the grant just made.
            granted_other_user = await manager.get_user(
                contract_harness.other_user.id, contract_harness.admin_user
            )
            assert (
                await manager.get_collection(
                    contract_harness.private_collection.identifier,
                    granted_other_user,
                )
                is not None
            )
        else:
            with pytest.raises(CapabilityNotSupported):
                await manager.grant_collection_access(
                    granting_user=contract_harness.owner_user,
                    target_user_id=contract_harness.other_user.id,
                    collection=contract_harness.private_collection,
                    role="viewer",
                )

        if capabilities.supports_revoking_access:
            if capabilities.supports_granting_access:
                await manager.revoke_collection_access(
                    revoking_user=contract_harness.owner_user,
                    target_user_id=contract_harness.other_user.id,
                    collection=contract_harness.private_collection,
                )
                revoked_other_user = await manager.get_user(
                    contract_harness.other_user.id, contract_harness.admin_user
                )
                assert (
                    await manager.get_collection(
                        contract_harness.private_collection.identifier,
                        revoked_other_user,
                    )
                    is None
                )
        else:
            with pytest.raises(CapabilityNotSupported):
                await manager.revoke_collection_access(
                    revoking_user=contract_harness.owner_user,
                    target_user_id=contract_harness.other_user.id,
                    collection=contract_harness.private_collection,
                )


class TestServerMetadata:
    @pytest.mark.asyncio
    async def test_get_server_metadata(self, contract_harness):
        result = await contract_harness.manager.get_server_metadata()
        assert result.title == contract_harness.server_metadata_title

    @pytest.mark.asyncio
    async def test_update_server_metadata(self, contract_harness):
        manager = contract_harness.manager
        capabilities = await manager.get_server_metadata_capabilities()
        to_update = ServerMetadataUpdate(title="Changed server title")
        if capabilities.supports_modification:
            updated = await manager.update_server_metadata(
                to_update, contract_harness.admin_user
            )
            assert updated.title == "Changed server title"
        else:
            with pytest.raises(CapabilityNotSupported):
                await manager.update_server_metadata(
                    to_update, contract_harness.admin_user
                )


class TestUserAccounts:
    @pytest.mark.asyncio
    async def test_get_user(self, contract_harness):
        manager = contract_harness.manager
        result = await manager.get_user(
            contract_harness.owner_user.id, contract_harness.admin_user
        )
        assert result is not None
        assert result.id == contract_harness.owner_user.id
        assert (
            await manager.get_user("does-not-exist-xyz", contract_harness.admin_user)
            is None
        )

    @pytest.mark.asyncio
    async def test_get_user_denied_for_anonymous(self, contract_harness):
        with pytest.raises(PottoCannotViewUserException):
            await contract_harness.manager.get_user(
                contract_harness.owner_user.id, None
            )

    @pytest.mark.asyncio
    async def test_get_user_allowed_for_any_authenticated_user(self, contract_harness):
        result = await contract_harness.manager.get_user(
            contract_harness.owner_user.id, contract_harness.other_user
        )
        assert result is not None
        assert result.id == contract_harness.owner_user.id

    @pytest.mark.asyncio
    async def test_get_user_by_username(self, contract_harness):
        manager = contract_harness.manager
        result = await manager.get_user_by_username(
            contract_harness.owner_user.username, contract_harness.admin_user
        )
        assert result is not None
        assert result.id == contract_harness.owner_user.id
        assert (
            await manager.get_user_by_username(
                "does-not-exist-xyz", contract_harness.admin_user
            )
            is None
        )

    @pytest.mark.asyncio
    async def test_get_user_by_username_denied_for_anonymous(self, contract_harness):
        with pytest.raises(PottoCannotViewUserException):
            await contract_harness.manager.get_user_by_username(
                contract_harness.owner_user.username, None
            )

    @pytest.mark.asyncio
    async def test_paginated_list_users_username_filter(self, contract_harness):
        results, total = await contract_harness.manager.paginated_list_users(
            include_total=True,
            filter_=UserFilter(username=contract_harness.owner_user.username),
            requesting_user=contract_harness.admin_user,
        )
        assert total == 1
        assert results[0].id == contract_harness.owner_user.id

    @pytest.mark.asyncio
    async def test_paginated_list_users_admin_filter(self, contract_harness):
        results, total = await contract_harness.manager.paginated_list_users(
            include_total=True,
            filter_=UserFilter(is_admin=True),
            requesting_user=contract_harness.admin_user,
        )
        assert total == 1
        assert results[0].id == contract_harness.admin_user.id

    @pytest.mark.asyncio
    async def test_paginated_list_users_denied_for_anonymous(self, contract_harness):
        with pytest.raises(PottoCannotViewUserException):
            await contract_harness.manager.paginated_list_users(
                include_total=True, requesting_user=None
            )

    @pytest.mark.asyncio
    async def test_paginated_list_users_allowed_for_any_authenticated_user(
        self, contract_harness
    ):
        results, total = await contract_harness.manager.paginated_list_users(
            include_total=True, requesting_user=contract_harness.other_user
        )
        assert total is not None

    @pytest.mark.asyncio
    async def test_pagination_consistent_with_total(self, contract_harness):
        manager = contract_harness.manager
        admin_user = contract_harness.admin_user
        all_results, total = await manager.paginated_list_users(
            page=1, page_size=1000, include_total=True, requesting_user=admin_user
        )
        assert total == len(all_results)
        assert total >= 6
        page_1, _ = await manager.paginated_list_users(
            page=1, page_size=2, requesting_user=admin_user
        )
        page_2, _ = await manager.paginated_list_users(
            page=2, page_size=2, requesting_user=admin_user
        )
        combined_ids = [u.id for u in page_1 + page_2]
        expected_ids = [u.id for u in all_results[: len(page_1) + len(page_2)]]
        assert combined_ids == expected_ids

    @pytest.mark.asyncio
    async def test_create_update_delete_user_capabilities(self, contract_harness):
        manager = contract_harness.manager
        capabilities = await manager.get_user_account_capabilities()

        if capabilities.supports_creation:
            created = await manager.create_user(
                UserCreate(
                    username="contract-new-user", password=SecretStr("newuserpass1")
                ),
                contract_harness.admin_user,
            )
            assert created.username == "contract-new-user"
            target_user_id = created.id
        else:
            with pytest.raises(CapabilityNotSupported):
                await manager.create_user(
                    UserCreate(
                        username="contract-new-user", password=SecretStr("newuserpass1")
                    ),
                    contract_harness.admin_user,
                )
            target_user_id = contract_harness.other_user.id

        if capabilities.supports_modification:
            updated = await manager.update_user(
                target_user_id,
                UserUpdate(email="new-email@example.com"),
                contract_harness.admin_user,
            )
            assert updated.email == "new-email@example.com"
            with pytest.raises(PottoCannotEditUserException):
                await manager.update_user(
                    target_user_id,
                    UserUpdate(email="denied@example.com"),
                    contract_harness.other_user,
                )
            with pytest.raises(PottoCannotEditUserException):
                await manager.update_user(
                    target_user_id,
                    UserUpdate(password="takeover12345"),
                    contract_harness.other_user,
                )
        else:
            with pytest.raises(CapabilityNotSupported):
                await manager.update_user(
                    target_user_id,
                    UserUpdate(email="new-email@example.com"),
                    contract_harness.admin_user,
                )

        if capabilities.supports_deletion:
            with pytest.raises(PottoCannotDeleteUserException):
                await manager.delete_user(target_user_id, contract_harness.other_user)
            await manager.delete_user(target_user_id, contract_harness.admin_user)
            assert (
                await manager.get_user(target_user_id, contract_harness.admin_user)
                is None
            )
        else:
            with pytest.raises(CapabilityNotSupported):
                await manager.delete_user(target_user_id, contract_harness.admin_user)


class TestAuthentication:
    @pytest.mark.asyncio
    async def test_authenticate_success(self, contract_harness):
        result = await contract_harness.manager.authenticate(
            contract_harness.owner_user.username, contract_harness.owner_user_password
        )
        assert result is not None
        assert result.id == contract_harness.owner_user.id

    @pytest.mark.asyncio
    async def test_authenticate_wrong_password(self, contract_harness):
        result = await contract_harness.manager.authenticate(
            contract_harness.owner_user.username, "definitely-wrong-password"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_unknown_username(self, contract_harness):
        result = await contract_harness.manager.authenticate(
            "does-not-exist-xyz", "whatever12345"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_inactive_user(self, contract_harness):
        result = await contract_harness.manager.authenticate(
            contract_harness.inactive_user.username,
            contract_harness.inactive_user_password,
        )
        assert result is None


class TestResourceEditorsAndViewers:
    @pytest.mark.asyncio
    async def test_list_resource_editors(self, contract_harness):
        editors = await contract_harness.manager.list_resource_editors(
            "collection",
            contract_harness.private_collection.identifier,
            contract_harness.admin_user,
        )
        assert contract_harness.editor_user.id in {u.id for u in editors}

    @pytest.mark.asyncio
    async def test_list_resource_viewers(self, contract_harness):
        viewers = await contract_harness.manager.list_resource_viewers(
            "collection",
            contract_harness.private_collection.identifier,
            contract_harness.admin_user,
        )
        assert contract_harness.viewer_user.id in {u.id for u in viewers}

    @pytest.mark.asyncio
    async def test_list_resource_editors_allowed_for_any_authenticated_user(
        self, contract_harness
    ):
        editors = await contract_harness.manager.list_resource_editors(
            "collection",
            contract_harness.private_collection.identifier,
            contract_harness.other_user,
        )
        assert contract_harness.editor_user.id in {u.id for u in editors}

    @pytest.mark.asyncio
    async def test_list_resource_editors_denied_for_anonymous(self, contract_harness):
        with pytest.raises(PottoCannotViewUserException):
            await contract_harness.manager.list_resource_editors(
                "collection", contract_harness.private_collection.identifier, None
            )

    @pytest.mark.asyncio
    async def test_list_resource_viewers_denied_for_anonymous(self, contract_harness):
        with pytest.raises(PottoCannotViewUserException):
            await contract_harness.manager.list_resource_viewers(
                "collection", contract_harness.private_collection.identifier, None
            )

    @pytest.mark.asyncio
    async def test_list_resource_editors_unsupported_resource_type(
        self, contract_harness
    ):
        with pytest.raises(NotImplementedError):
            await contract_harness.manager.list_resource_editors(
                "process", "some-process", contract_harness.admin_user
            )


class TestCommon:
    @pytest.mark.asyncio
    async def test_check_health_ok(self, contract_harness):
        assert await contract_harness.manager.check_health() == "ok"

    def test_potto_cli_group_is_nonempty_string(self, contract_harness):
        group = contract_harness.manager.potto_cli_group
        assert isinstance(group, str)
        assert group

    @pytest.mark.asyncio
    async def test_get_cli_group_returns_app_or_none(self, contract_harness):
        result = await contract_harness.manager.get_cli_group()
        assert result is None or hasattr(result, "command")
