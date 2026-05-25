import pytest
from sqlalchemy.exc import IntegrityError

from potto.db.commands import collections as collection_commands
from potto.schemas import (
    base as base_schemas,
    collections as collection_schemas,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_bare_collection_create(db_session_maker, admin_user):
    to_create = collection_schemas.CollectionCreate(
        resource_identifier="res1",
        owner_id=admin_user.id,
        is_public=False,
        collection_type=base_schemas.CollectionType.FEATURE_COLLECTION,
        title="Fake collection title",
    )
    async with db_session_maker() as session:
        db_collection = await collection_commands.create_collection(session, to_create)
        assert db_collection.id is not None


@pytest.mark.asyncio
async def test_collection_create_fails_on_duplicate_identifier(
    db_session_maker, admin_user
):
    first_to_create = collection_schemas.CollectionCreate(
        resource_identifier="res1",
        owner_id=admin_user.id,
        is_public=False,
        collection_type=base_schemas.CollectionType.FEATURE_COLLECTION,
        title="Fake collection title",
    )
    second_to_create = collection_schemas.CollectionCreate(
        resource_identifier="res1",
        owner_id=admin_user.id,
        is_public=False,
        collection_type=base_schemas.CollectionType.FEATURE_COLLECTION,
        title="Another fake collection title",
    )
    async with db_session_maker() as session:
        await collection_commands.create_collection(session, first_to_create)
        with pytest.raises(IntegrityError):
            await collection_commands.create_collection(session, second_to_create)


@pytest.mark.asyncio
async def test_collection_create_no_temporal_extent(db_session_maker, admin_user):
    to_create = collection_schemas.CollectionCreate(
        resource_identifier="res1",
        owner_id=admin_user.id,
        is_public=False,
        collection_type=base_schemas.CollectionType.FEATURE_COLLECTION,
        title="Fake collection title",
        spatial_extent="POLYGON ((30 10, 40 40, 20 40, 10 20, 30 10))",
        spatial_extent_crs="http://www.opengis.net/def/crs/OGC/1.3/CRS84",
        providers={
            "feature": base_schemas.PottoProvider(
                provider_name="pygeoapi",
                config={"python_callable": "fake", "data": None, "options": {}},
            )
        },
    )
    async with db_session_maker() as session:
        db_collection = await collection_commands.create_collection(session, to_create)
        assert db_collection.id is not None
