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
    Job,
    User,
)
from .common import _get_total_num_records

logger = logging.getLogger(__name__)


async def collect_all_public_jobs(session: AsyncSession) -> list[Job]:
    _, num_total = await list_public_jobs(
        session,
        limit=1,
        include_total=True,
    )
    assert num_total is not None
    items, _ = await list_public_jobs(
        session,
        limit=num_total,
        include_total=False,
    )
    return items


async def collect_all_user_jobs(
    session: AsyncSession,
    user_id: str | None = None,
    accessible_identifiers: list[str] | None = None,
) -> list[Job]:
    _, num_total = await list_user_jobs(
        session,
        limit=1,
        user_id=user_id,
        accessible_identifiers=accessible_identifiers,
        include_total=True,
    )
    assert num_total is not None
    items, _ = await list_user_jobs(
        session,
        limit=num_total,
        user_id=user_id,
        accessible_identifiers=accessible_identifiers,
        include_total=False,
    )
    return items


async def paginated_list_all_jobs(
    session: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    include_total: bool = False,
    identifier_filter: str | None = None,
) -> tuple[list[Job], int | None]:
    limit = page_size
    offset = limit * (page - 1)
    return await list_user_jobs(
        session,
        limit=limit,
        offset=offset,
        include_total=include_total,
        user_id=None,
        identifier_filter=identifier_filter,
    )


async def paginated_list_public_jobs(
    session: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    include_total: bool = False,
    identifier_filter: str | None = None,
) -> tuple[list[Job], int | None]:
    limit = page_size
    offset = limit * (page - 1)
    return await list_public_jobs(
        session,
        limit=limit,
        offset=offset,
        include_total=include_total,
        identifier_filter=identifier_filter,
    )


async def paginated_list_user_jobs(
    session: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    include_total: bool = False,
    user_id: str | None = None,
    accessible_identifiers: list[int] | None = None,
    identifier_filter: str | None = None,
) -> tuple[list[Job], int | None]:
    limit = page_size
    offset = limit * (page - 1)
    return await list_user_jobs(
        session,
        limit=limit,
        offset=offset,
        include_total=include_total,
        user_id=user_id,
        accessible_identifiers=accessible_identifiers,
        identifier_filter=identifier_filter,
    )


async def list_public_jobs(
    session: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
    include_total: bool = False,
) -> tuple[list[Job], int | None]:
    logger.debug(f"{locals()=}")
    statement = (
        select(Job)
        .options(
            selectinload(cast(QueryableAttribute, Job.owner)),
            selectinload(cast(QueryableAttribute, Job.process)),
        )
        .where(Job.is_public)
        .order_by(Job.created_at)
    )
    logger.debug(f"{str(statement)=}")
    items = (await session.exec(statement.offset(offset).limit(limit))).all()
    num_total = (
        await _get_total_num_records(session, statement) if include_total else None
    )
    return items, num_total


async def list_user_jobs(
    session: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
    include_total: bool = False,
    user_id: str | None = None,
    accessible_identifiers: list[int] | None = None,
) -> tuple[list[Job], int | None]:
    """List jobs visible to an authenticated user.

    - accessible_identifiers=None: admin mode, all jobs are returned.
    - accessible_identifiers=[...]: returns public jobs, jobs owned
      by user_id, and jobs whose identifier is in accessible_identifiers.
    """
    logger.debug(f"{locals()=}")
    statement = select(Job).options(
        selectinload(cast(QueryableAttribute, Job.owner)),
        selectinload(cast(QueryableAttribute, Job.process)),
    )
    if accessible_identifiers is not None:
        statement = statement.where(
            or_(
                Job.is_public,
                Job.owner_id == user_id,
                Job.resource_identifier.in_(accessible_identifiers),  # ty: ignore[unresolved-attribute]
            )
        ).order_by(Job.created_at)
    items = (await session.exec(statement.offset(offset).limit(limit))).all()
    num_total = (
        await _get_total_num_records(session, statement) if include_total else None
    )
    return items, num_total


async def get_job(
    session: AsyncSession,
    job_id: int,
) -> Job | None:
    statement = (
        select(Job)
        .options(
            selectinload(cast(QueryableAttribute, Job.owner)),
            selectinload(cast(QueryableAttribute, Job.process)),
        )
        .where(Job.id == job_id)
    )
    return (await session.exec(statement)).first()


async def get_job_editors(
    session: AsyncSession,
    job_id: int,
) -> list[User]:
    statement = select(User).where(
        User.scopes.contains([f"job-{job_id}:editor"])  # ty: ignore[unresolved-attribute]
    )
    return list((await session.exec(statement)).all())


async def get_job_viewers(
    session: AsyncSession,
    job_id: int,
) -> list[User]:
    statement = select(User).where(
        User.scopes.contains([f"job-{job_id}:viewer"])  # ty: ignore[unresolved-attribute]
    )
    return list((await session.exec(statement)).all())


async def get_owned_job_identifiers(
    session: AsyncSession,
    user_id: str,
) -> list[str]:
    statement = select(Job.id).where(Job.owner_id == user_id)
    return list((await session.exec(statement)).all())
