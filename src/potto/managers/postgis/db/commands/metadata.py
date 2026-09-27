import logging

from sqlmodel.ext.asyncio.session import AsyncSession

from .....exceptions import (
    CannotCreateResourceException,
    ResourceNotFoundException,
)
from .....schemas.metadata import (
    ServerMetadataCreate,
    ServerMetadataUpdate,
)
from ..models import ServerMetadata
from ..queries import get_metadata

logger = logging.getLogger(__name__)


async def create_metadata(
    session: AsyncSession, to_create: ServerMetadataCreate
) -> ServerMetadata:
    instance = ServerMetadata.model_validate(to_create.model_dump(exclude_none=True))
    session.add(instance)
    await session.commit()
    await session.refresh(instance)
    if (created := await get_metadata(session)) is None:
        raise CannotCreateResourceException("error creating metadata")
    return created


async def update_metadata(
    session: AsyncSession,
    db_metadata: ServerMetadata,
    to_update: ServerMetadataUpdate,
) -> ServerMetadata:
    for key, value in to_update.model_dump(exclude_unset=True).items():
        setattr(db_metadata, key, value)
    session.add(db_metadata)
    await session.commit()
    await session.refresh(db_metadata)
    return db_metadata


async def delete_metadata(
    session: AsyncSession,
) -> None:
    if instance := (await get_metadata(session)):
        await session.delete(instance)
        await session.commit()
    else:
        raise ResourceNotFoundException("Server metadata not found.")
