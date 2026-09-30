"""Permission-checked business logic backing ``PostgisManager``.

The functions defined in this module always return instances of potto's public,
storage-agnostic schemas (``potto.schemas.*``), never this package's private ORM
models.
"""

import logging
from typing import cast

from sqlalchemy.exc import DatabaseError
from sqlmodel.ext.asyncio.session import AsyncSession

from ....authz.authorizer import (
    PottoAuthorizer,
    Principal,
    SystemPrincipal,
)
from .... import exceptions
from ....schemas.jobs import (
    Job as JobSchema,
    JobCreate,
)
from ..db.queries import jobs as job_queries
from ..db.commands import jobs as job_commands

logger = logging.getLogger(__name__)


async def paginated_list_jobs(
    session: AsyncSession,
    user: Principal | None,
    authorizer: PottoAuthorizer,
    *,
    page: int = 1,
    page_size: int = 20,
    include_total: bool = False,
) -> tuple[list[JobSchema], int | None]:
    """Produce a paginated list of all jobs that the user has access to."""
    if user is None:
        (
            public_jobs,
            count,
        ) = await job_queries.paginated_list_public_jobs(
            session,
            page=page,
            page_size=page_size,
            include_total=include_total,
        )
        return [i.to_potto() for i in public_jobs], count
    match user:
        case SystemPrincipal():
            (
                accessible_jobs,
                count,
            ) = await job_queries.paginated_list_all_jobs(
                session,
                page=page,
                page_size=page_size,
                include_total=include_total,
            )
        case _:
            accessible_ids = await authorizer.get_accessible_job_identifiers(user)
            (
                accessible_jobs,
                count,
            ) = await job_queries.paginated_list_user_jobs(
                session,
                page=page,
                page_size=page_size,
                include_total=include_total,
                user_id=user.id,
                accessible_identifiers=accessible_ids,
            )
    return [item.to_potto() for item in accessible_jobs], count


async def get_job(
    session: AsyncSession,
    user: Principal | None,
    authorizer: PottoAuthorizer,
    identifier: int,
) -> JobSchema | None:
    resource = await job_queries.get_job(
        session, identifier
    )
    if resource is None:
        return None
    job = resource.to_potto()
    if not await authorizer.can_view_job(user, job):
        return None
    return job


async def create_job(
    session: AsyncSession,
    user: Principal | None,
    authorizer: PottoAuthorizer,
    to_create: JobCreate,
) -> JobSchema:
    if not await authorizer.can_create_job(user):
        raise exceptions.CannotCreateResourceError(
            "User does not have permission to create a job."
        )
    try:
        created = await job_commands.create_job(session, to_create)
    except DatabaseError as err:
        await session.rollback()
        raise exceptions.CannotCreateResourceError(str(err)) from err
    return created.to_potto()


async def delete_job(
    session: AsyncSession,
    user: Principal,
    authorizer: PottoAuthorizer,
    identifier: int,
) -> None:
    db_job = await job_queries.get_job(
        session, identifier
    )
    if db_job is None:
        raise exceptions.ResourceNotFoundError(
            f"job {identifier!r} does not exist."
        )
    if not await authorizer.can_delete_job(user, db_job.to_potto()):
        raise exceptions.CannotDeleteResourceError(
            f"User does not have permission to delete job {identifier!r}."
        )
    try:
        return await job_commands.delete_job(session, cast(int, db_job.id))
    except DatabaseError as err:
        raise exceptions.CannotDeleteResourceError(str(err)) from err
