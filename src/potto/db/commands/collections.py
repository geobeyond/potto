import logging

from sqlmodel.ext.asyncio.session import AsyncSession

from ... import constants
from ...exceptions import PottoException
from ...schemas.collections import (
    CollectionCreate,
    CollectionUpdate,
)
from ..models import Collection
from ..queries import get_collection

logger = logging.getLogger(__name__)


async def create_collection(
    session: AsyncSession, to_create: CollectionCreate
) -> Collection:
    logger.debug(f"{to_create=}")
    collection_kwargs = to_create.model_dump(exclude={"additional_extents"})
    collection_kwargs["crs"] = to_create.crs or [constants.CRS_84]
    instance = Collection(**collection_kwargs)
    for additional_extent in instance.additional_extents or []:
        instance.additional_extents[additional_extent.name] = (
            additional_extent.model_dump(exclude={"name"})
        )
    session.add(instance)
    await session.commit()
    await session.refresh(instance)
    assert instance.id is not None
    if (created := await get_collection(session, instance.id)) is None:
        raise PottoException("error creating collection")
    return created


async def update_collection(
    session: AsyncSession,
    db_collection: Collection,
    to_update: CollectionUpdate,
) -> Collection:
    updates = to_update.model_dump(
        exclude={"additional_extents"},
        exclude_unset=True,
    )
    if "crs" in updates and updates["crs"] is None:
        updates["crs"] = [constants.CRS_84]
    if "storage_crs" in updates and updates["storage_crs"] is None:
        updates["storage_crs"] = constants.CRS_84
    for key, value in updates.items():
        setattr(db_collection, key, value)
    if to_update.additional_extents is not None:
        db_collection.additional_extents = {}
        for additional_extent in to_update.additional_extents or []:
            db_collection.additional_extents[additional_extent.name] = (
                additional_extent.model_dump(exclude={"name"}, exclude_none=True)
            )
    session.add(db_collection)
    await session.commit()
    await session.refresh(db_collection)
    return db_collection


async def delete_collection(
    session: AsyncSession,
    collection_id: int,
) -> None:
    if instance := (await get_collection(session, collection_id)):
        await session.delete(instance)
        await session.commit()
    else:
        raise PottoException(f"Collection with id {collection_id} does not exist.")
