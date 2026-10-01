import logging
from typing import (
    Sequence,
    cast,
)

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
    Process,
    User,
)
from .common import _get_total_num_records

logger = logging.getLogger(__name__)


async def paginated_list_all_jobs(
    session: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    include_total: bool = False,
    identifiers_filter: Sequence[str] | None = None,
) -> tuple[list[Job], int | None]:
    limit = page_size
    offset = limit * (page - 1)
    return await list_user_jobs(
        session,
        limit=limit,
        offset=offset,
        include_total=include_total,
        user_id=None,
        accessible_job_identifiers=None,
        accessible_process_identifiers=None,
        identifiers_filter=identifiers_filter,
    )


async def paginated_list_public_jobs(
    session: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    include_total: bool = False,
    identifiers_filter: Sequence[str] | None = None,
) -> tuple[list[Job], int | None]:
    limit = page_size
    offset = limit * (page - 1)
    return await list_public_jobs(
        session,
        limit=limit,
        offset=offset,
        include_total=include_total,
        identifiers_filter=identifiers_filter,
    )


async def paginated_list_user_jobs(
    session: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    include_total: bool = False,
    user_id: str | None = None,
    accessible_job_identifiers: list[str] | None = None,
    accessible_process_identifiers: list[str] | None = None,
    identifiers_filter: Sequence[str] | None = None,
) -> tuple[list[Job], int | None]:
    limit = page_size
    offset = limit * (page - 1)
    return await list_user_jobs(
        session,
        limit=limit,
        offset=offset,
        include_total=include_total,
        user_id=user_id,
        accessible_job_identifiers=accessible_job_identifiers,
        accessible_process_identifiers=accessible_process_identifiers,
        identifiers_filter=identifiers_filter,
    )


async def list_public_jobs(
    session: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
    include_total: bool = False,
    identifiers_filter: Sequence[str] | None = None,
) -> tuple[list[Job], int | None]:
    logger.debug(f"{locals()=}")
    statement = _base_select().where(Job.is_public)
    statement = _apply_common_filters(statement, identifiers_filter)
    statement = _apply_ordering(statement)
    items = (await session.exec(statement.offset(offset).limit(limit))).all()
    num_total = (
        await _get_total_num_records(session, statement) if include_total else None
    )
    return list(items), num_total


async def list_user_jobs(
    session: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
    include_total: bool = False,
    user_id: str | None = None,
    accessible_job_identifiers: list[str] | None = None,
    accessible_process_identifiers: list[str] | None = None,
    identifiers_filter: Sequence[str] | None = None,
) -> tuple[list[Job], int | None]:
    """List jobs visible to an authenticated user.

    - accessible_job_identifiers=None and accessible_process_identifiers=None:
      admin mode, all jobs are returned.
    - otherwise, returns public jobs, jobs owned by user_id, jobs whose identifier
      is in accessible_job_identifiers and, since jobs inherit the sharing of their
      parent process, jobs of processes that are either owned by user_id or whose
      identifier is in accessible_process_identifiers.
    """
    logger.debug(f"{locals()=}")
    statement = _base_select()
    if (
        accessible_job_identifiers is not None
        or accessible_process_identifiers is not None
    ):
        statement = statement.join(Process).where(
            or_(
                Job.is_public,
                Job.owner_id == user_id,
                Job.resource_identifier.in_(accessible_job_identifiers or []),  # ty: ignore[unresolved-attribute]
                Process.owner_id == user_id,
                Process.resource_identifier.in_(accessible_process_identifiers or []),  # ty: ignore[unresolved-attribute]
            )
        )
    statement = _apply_common_filters(statement, identifiers_filter)
    statement = _apply_ordering(statement)
    items = (await session.exec(statement.offset(offset).limit(limit))).all()
    num_total = (
        await _get_total_num_records(session, statement) if include_total else None
    )
    return list(items), num_total


def _base_select():
    return select(Job).options(
        selectinload(cast(QueryableAttribute, Job.owner)),
        selectinload(cast(QueryableAttribute, Job.process)).selectinload(
            cast(QueryableAttribute, Process.owner)
        ),
    )


def _apply_common_filters(
    statement,
    identifiers_filter: Sequence[str] | None,
):
    if identifiers_filter:
        statement = statement.where(
            Job.resource_identifier.in_(identifiers_filter)  # ty: ignore[unresolved-attribute]
        )
    return statement


def _apply_ordering(statement):
    return statement.order_by(Job.created_at, Job.id)


async def get_job(
    session: AsyncSession,
    resource_identifier: str,
) -> Job | None:
    statement = _base_select().where(Job.resource_identifier == resource_identifier)
    return (await session.exec(statement)).first()


async def get_job_editors(
    session: AsyncSession,
    resource_identifier: str,
) -> list[User]:
    statement = select(User).where(
        User.scopes.contains([f"job-{resource_identifier}:editor"])  # ty: ignore[unresolved-attribute]
    )
    return list((await session.exec(statement)).all())


async def get_job_viewers(
    session: AsyncSession,
    resource_identifier: str,
) -> list[User]:
    statement = select(User).where(
        User.scopes.contains([f"job-{resource_identifier}:viewer"])  # ty: ignore[unresolved-attribute]
    )
    return list((await session.exec(statement)).all())
