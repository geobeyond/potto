import logging
from typing import cast

from sqlmodel.ext.asyncio.session import AsyncSession

from .....exceptions import (
    CannotCreateResourceException,
    CannotUpdateResourceException,
    ResourceNotFoundException,
)
from .....schemas.processes import (
    ProcessCreate,
    ProcessUpdate,
)
from ..models import Process
from ..queries.processes import get_process

logger = logging.getLogger(__name__)


async def create_process(session: AsyncSession, to_create: ProcessCreate) -> Process:
    logger.debug(f"{to_create=}")
    instance_kwargs = to_create.model_dump()
    instance = Process(**instance_kwargs)
    session.add(instance)
    await session.commit()
    await session.refresh(instance)
    if (created := await get_process(session, cast(int, instance.id))) is None:
        raise CannotCreateResourceException("error creating process")
    return created


async def update_process(
    session: AsyncSession,
    db_process: Process,
    to_update: ProcessUpdate,
) -> Process:
    updates = to_update.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(db_process, key, value)
    session.add(db_process)
    await session.commit()
    await session.refresh(db_process)
    if (updated := await get_process(session, cast(int, db_process.id))) is None:
        raise CannotUpdateResourceException(
            f"error updating collection {db_process.id}"
        )
    return updated


async def delete_process(
    session: AsyncSession,
    process_id: int,
) -> None:
    if instance := (await get_process(session, process_id)):
        await session.delete(instance)
        await session.commit()
    else:
        raise ResourceNotFoundException(f"Process with id {process_id} does not exist.")
