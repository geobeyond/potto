"""Shared harness for the manager-protocol contract-test suite.

Registered as a pytest plugin from conftest.py's ``pytest_plugins`` (same pattern as
``tests/live_server.py``), so the fixtures defined here are available to any test
module without an explicit import.

Builds a ``ManagerContractHarness`` - the same shape of role-based test data (an
admin, a collection owner, a viewer, an editor, an unrelated user, an inactive user,
a public collection, a private collection, a public collection with a spatial extent
intersecting a known test point, and a public collection with a spatial extent that
does *not* intersect it) - from each manager backend, so
``tests/test_manager_contract.py`` can run identical assertions against both without
caring which one is actually under test.
"""

import dataclasses
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from pydantic import SecretStr

from potto.constants import CollectionType, CRS_84
from potto.managers.configurationfile.manager import get_configuration_file_manager
from potto.schemas.auth import PottoScope, PottoUser, UserCreate, UserUpdate
from potto.schemas.collections import Collection, CollectionCreate
from potto.schemas.metadata import ServerMetadataUpdate
from potto.schemas.processes import (
    ExecutionUnitOtherCreate,
    Process,
    ProcessCreate,
    ProcessDescriptionCreate,
)

SAMPLE_CONFIG_FILE = (
    Path(__file__).parent / "data" / "configurationfile" / "sample_config.toml"
)

# Shared between both backends so spatial_intersect contract assertions compare
# against the same geometries regardless of which manager built the collections.
SPATIAL_EXTENT_WKT = "POLYGON ((-10 40, -10 50, 5 50, 5 40, -10 40))"
DISTANT_EXTENT_WKT = "POLYGON ((100 -40, 100 -30, 120 -30, 120 -40, 100 -40))"


@dataclasses.dataclass
class ManagerContractHarness:
    manager: Any
    admin_user: PottoUser
    owner_user: PottoUser
    owner_user_password: str
    viewer_user: PottoUser
    editor_user: PottoUser
    other_user: PottoUser
    inactive_user: PottoUser
    inactive_user_password: str
    public_collection: Collection
    private_collection: Collection
    spatial_collection: Collection
    distant_collection: Collection
    public_process: Process
    private_process: Process
    server_metadata_title: str


@pytest_asyncio.fixture
async def configurationfile_contract_harness(settings) -> ManagerContractHarness:
    manager = get_configuration_file_manager(
        {"config_file": SAMPLE_CONFIG_FILE}, settings
    )
    users = manager.user_accounts
    return ManagerContractHarness(
        manager=manager,
        admin_user=users["admin-1"],
        owner_user=users["user-1"],
        owner_user_password="alicepass",
        viewer_user=users["user-2"],
        editor_user=users["user-4"],
        other_user=users["user-5"],
        inactive_user=users["user-3"],
        inactive_user_password="carolpass",
        public_collection=manager.collections["public-collection"],
        private_collection=manager.collections["private-collection"],
        spatial_collection=manager.collections["geo-collection"],
        distant_collection=manager.collections["distant-collection"],
        public_process=manager.processes["public-process"],
        private_process=manager.processes["private-process"],
        server_metadata_title=manager.server_metadata.title,
    )


@pytest_asyncio.fixture
async def postgis_contract_harness(db, settings) -> ManagerContractHarness:
    user_manager = settings.get_user_account_manager()
    collection_manager = settings.get_collection_manager()
    process_manager = settings.get_process_manager()
    metadata_manager = settings.get_server_metadata_manager()

    # A trusted bootstrap caller, analogous to conftest.py's `admin_user` fixture -
    # there is no admin yet to authorize creating the very first one.
    bootstrap_user = PottoUser(
        id="contract-bootstrap",
        username="contract-bootstrap",
        is_active=True,
        scopes=[PottoScope.ADMIN.value],
    )

    admin_user = await user_manager.create_user(
        UserCreate(
            username="contract-admin",
            scopes=[PottoScope.ADMIN],
            password=SecretStr("adminpass1"),
        ),
        bootstrap_user,
    )
    owner_user = await user_manager.create_user(
        UserCreate(username="contract-owner", password=SecretStr("ownerpass1")),
        admin_user,
    )
    viewer_user = await user_manager.create_user(
        UserCreate(username="contract-viewer", password=SecretStr("viewerpass1")),
        admin_user,
    )
    editor_user = await user_manager.create_user(
        UserCreate(username="contract-editor", password=SecretStr("editorpass1")),
        admin_user,
    )
    other_user = await user_manager.create_user(
        UserCreate(username="contract-other", password=SecretStr("otherpass1")),
        admin_user,
    )
    inactive_user = await user_manager.create_user(
        UserCreate(username="contract-inactive", password=SecretStr("inactivepass1")),
        admin_user,
    )
    inactive_user = await user_manager.update_user(
        inactive_user.id, UserUpdate(is_active=False), admin_user
    )

    public_collection = await collection_manager.create_collection(
        CollectionCreate(
            resource_identifier="contract-public",
            owner_id=owner_user.id,
            is_public=True,
            collection_type=CollectionType.FEATURE_COLLECTION,
            title="Contract public collection",
        ),
        owner_user,
    )
    private_collection = await collection_manager.create_collection(
        CollectionCreate(
            resource_identifier="contract-private",
            owner_id=owner_user.id,
            is_public=False,
            collection_type=CollectionType.FEATURE_COLLECTION,
            title="Contract private collection",
        ),
        owner_user,
    )
    spatial_collection = await collection_manager.create_collection(
        CollectionCreate(
            resource_identifier="contract-spatial",
            owner_id=owner_user.id,
            is_public=True,
            collection_type=CollectionType.FEATURE_COLLECTION,
            title="Contract spatial collection",
            spatial_extent=SPATIAL_EXTENT_WKT,
            spatial_extent_crs=CRS_84,
        ),
        owner_user,
    )
    distant_collection = await collection_manager.create_collection(
        CollectionCreate(
            resource_identifier="contract-distant",
            owner_id=owner_user.id,
            is_public=True,
            collection_type=CollectionType.FEATURE_COLLECTION,
            title="Contract distant collection",
            spatial_extent=DISTANT_EXTENT_WKT,
            spatial_extent_crs=CRS_84,
        ),
        owner_user,
    )

    await collection_manager.grant_collection_access(
        granting_user=owner_user,
        target_user_id=viewer_user.id,
        collection=private_collection,
        role="viewer",
    )
    await collection_manager.grant_collection_access(
        granting_user=owner_user,
        target_user_id=editor_user.id,
        collection=private_collection,
        role="editor",
    )
    # Re-fetch: authorization checks read `user.scopes` off the object it's given,
    # not a fresh DB row, and the objects above are now stale (their in-memory
    # `scopes` predate the grants just made).
    viewer_user = await user_manager.get_user(viewer_user.id, admin_user)
    editor_user = await user_manager.get_user(editor_user.id, admin_user)

    public_process = await process_manager.create_process(
        ProcessCreate(
            processDescription=ProcessDescriptionCreate(
                identifier="contract-public-process",
                title="Contract public process",
                owner_id=owner_user.id,
                is_public=True,
                version="1.0.0",
            ),
            execution_unit=ExecutionUnitOtherCreate(type_="other", value={}),
        ),
        owner_user,
    )
    private_process = await process_manager.create_process(
        ProcessCreate(
            processDescription=ProcessDescriptionCreate(
                identifier="contract-private-process",
                title="Contract private process",
                owner_id=owner_user.id,
                is_public=False,
                version="1.0.0",
            ),
            execution_unit=ExecutionUnitOtherCreate(type_="other", value={}),
        ),
        owner_user,
    )

    await process_manager.grant_process_access(
        granting_user=owner_user,
        target_user_id=viewer_user.id,
        process=private_process,
        role="viewer",
    )
    await process_manager.grant_process_access(
        granting_user=owner_user,
        target_user_id=editor_user.id,
        process=private_process,
        role="editor",
    )
    # Re-fetch again for the same reason as above, now that the process grants have
    # added more scopes on top of the collection ones.
    viewer_user = await user_manager.get_user(viewer_user.id, admin_user)
    editor_user = await user_manager.get_user(editor_user.id, admin_user)

    server_metadata_title = "Contract potto server"
    await metadata_manager.update_server_metadata(
        ServerMetadataUpdate(title=server_metadata_title), admin_user
    )

    return ManagerContractHarness(
        manager=collection_manager,
        admin_user=admin_user,
        owner_user=owner_user,
        owner_user_password="ownerpass1",
        viewer_user=viewer_user,
        editor_user=editor_user,
        other_user=other_user,
        inactive_user=inactive_user,
        inactive_user_password="inactivepass1",
        public_collection=public_collection,
        private_collection=private_collection,
        spatial_collection=spatial_collection,
        distant_collection=distant_collection,
        public_process=public_process,
        private_process=private_process,
        server_metadata_title=server_metadata_title,
    )


@pytest.fixture(
    params=[
        pytest.param("postgis", marks=pytest.mark.integration),
        "configurationfile",
    ]
)
def contract_harness(request) -> ManagerContractHarness:
    return request.getfixturevalue(f"{request.param}_contract_harness")
