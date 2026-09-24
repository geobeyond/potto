import logging
from typing import cast

from sqlalchemy.orm import (
    QueryableAttribute,
    selectinload,
)
from sqlmodel import (
    or_,
    select,
)
from sqlmodel.ext.asyncio.session import AsyncSession

from ..models import (
    Process,
    User,
)
from .common import _get_total_num_records

logger = logging.getLogger(__name__)


async def collect_all_public_processes(session: AsyncSession) -> list[Process]:
    _, num_total = await list_public_processes(
        session,
        limit=1,
        include_total=True,
    )
    assert num_total is not None
    items, _ = await list_public_processes(
        session,
        limit=num_total,
        include_total=False,
    )
    return items


async def collect_all_user_processes(
    session: AsyncSession,
    user_id: str | None = None,
    accessible_identifiers: list[str] | None = None,
) -> list[Process]:
    _, num_total = await list_user_processes(
        session,
        limit=1,
        user_id=user_id,
        accessible_identifiers=accessible_identifiers,
        include_total=True,
    )
    assert num_total is not None
    items, _ = await list_user_processes(
        session,
        limit=num_total,
        user_id=user_id,
        accessible_identifiers=accessible_identifiers,
        include_total=False,
    )
    return items


async def paginated_list_all_processes(
    session: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    include_total: bool = False,
    identifier_filter: str | None = None,
) -> tuple[list[Process], int | None]:
    limit = page_size
    offset = limit * (page - 1)
    return await list_user_processes(
        session,
        limit=limit,
        offset=offset,
        include_total=include_total,
        user_id=None,
        identifier_filter=identifier_filter,
    )


async def paginated_list_public_processes(
    session: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    include_total: bool = False,
    identifier_filter: str | None = None,
) -> tuple[list[Process], int | None]:
    limit = page_size
    offset = limit * (page - 1)
    return await list_public_processes(
        session,
        limit=limit,
        offset=offset,
        include_total=include_total,
        identifier_filter=identifier_filter,
    )


async def paginated_list_user_processes(
    session: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    include_total: bool = False,
    user_id: str | None = None,
    accessible_identifiers: list[str] | None = None,
    identifier_filter: str | None = None,
) -> tuple[list[Process], int | None]:
    limit = page_size
    offset = limit * (page - 1)
    return await list_user_processes(
        session,
        limit=limit,
        offset=offset,
        include_total=include_total,
        user_id=user_id,
        accessible_identifiers=accessible_identifiers,
        identifier_filter=identifier_filter,
    )


async def list_public_processes(
    session: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
    include_total: bool = False,
    identifier_filter: str | None = None,
) -> tuple[list[Process], int | None]:
    logger.debug(f"{locals()=}")
    statement = (
        select(Process)
        .options(selectinload(cast(QueryableAttribute, Process.owner)))
        .where(Process.is_public)
    )
    statement = _apply_common_filters(statement, identifier_filter)
    statement = statement.order_by(
        Process.created_at,
        Process.resource_identifier.desc().nullslast(),  # ty: ignore[unresolved-attribute]
    )
    logger.debug(f"{str(statement)=}")
    items = (await session.exec(statement.offset(offset).limit(limit))).all()
    num_total = (
        await _get_total_num_records(session, statement) if include_total else None
    )
    return items, num_total


async def list_user_processes(
    session: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
    include_total: bool = False,
    user_id: str | None = None,
    accessible_identifiers: list[str] | None = None,
    identifier_filter: str | None = None,
) -> tuple[list[Process], int | None]:
    """List processes visible to an authenticated user.

    - accessible_identifiers=None: admin mode, all processes are returned.
    - accessible_identifiers=[...]: returns public processes, processes owned
      by user_id, and processes whose identifier is in accessible_identifiers.
    """
    logger.debug(f"{locals()=}")
    statement = select(Process).options(
        selectinload(cast(QueryableAttribute, Process.owner))
    )
    if accessible_identifiers is not None:
        statement = statement.where(
            or_(
                Process.is_public,
                Process.owner_id == user_id,
                Process.resource_identifier.in_(accessible_identifiers),  # ty: ignore[unresolved-attribute]
            )
        )
    statement = _apply_common_filters(statement, identifier_filter)
    statement = statement.order_by(
        Process.created_at,
        Process.resource_identifier.desc().nullslast(),  # ty: ignore[unresolved-attribute]
    )
    items = (await session.exec(statement.offset(offset).limit(limit))).all()
    num_total = (
        await _get_total_num_records(session, statement) if include_total else None
    )
    return items, num_total


def _apply_common_filters(
    statement,
    identifier_filter: str | None,
):
    if identifier_filter:
        statement = statement.where(
            Process.resource_identifier.ilike(f"%{identifier_filter}%")  # ty: ignore[unresolved-attribute]
        )
    return statement


async def get_process(
    session: AsyncSession,
    process_id: int,
) -> Process | None:
    statement = (
        select(Process)
        .options(selectinload(cast(QueryableAttribute, Process.owner)))
        .where(Process.id == process_id)
    )
    return (await session.exec(statement)).first()


async def get_process_editors(
    session: AsyncSession,
    resource_identifier: str,
) -> list[User]:
    statement = select(User).where(
        User.scopes.contains([f"process-{resource_identifier}:editor"])  # ty: ignore[unresolved-attribute]
    )
    return list((await session.exec(statement)).all())


async def get_process_viewers(
    session: AsyncSession,
    resource_identifier: str,
) -> list[User]:
    statement = select(User).where(
        User.scopes.contains([f"process-{resource_identifier}:viewer"])  # ty: ignore[unresolved-attribute]
    )
    return list((await session.exec(statement)).all())


async def get_process_by_resource_identifier(
    session: AsyncSession,
    resource_identifier: str,
) -> Process | None:
    statement = (
        select(Process)
        .options(selectinload(cast(QueryableAttribute, Process.owner)))
        .where(Process.resource_identifier == resource_identifier)
    )
    return (await session.exec(statement)).first()


async def get_owned_process_identifiers(
    session: AsyncSession,
    user_id: str,
) -> list[str]:
    statement = select(Process.resource_identifier).where(Process.owner_id == user_id)
    return list((await session.exec(statement)).all())
