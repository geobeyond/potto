"""Permission-checked business logic backing ``PostgisManager``.

The functions defined in this module always return instances of potto's public,
storage-agnostic schemas (``potto.schemas.*``), never this package's private ORM
models.
"""

import logging
from typing import (
    Collection,
    Sequence,
    cast,
)

from sqlalchemy.exc import DatabaseError
from sqlmodel.ext.asyncio.session import AsyncSession

from ....authz.authorizer import (
    PottoAuthorizer,
    Principal,
    SystemPrincipal,
)
from .... import exceptions
from ....schemas.auth import PottoUser
from ....schemas.base import OgcApiException
from ....schemas.jobs import (
    Job as JobSchema,
    JobCreate,
    JobStatus,
)
from ....schemas.processes import ProcessDeploymentStatusValue
from ..db.commands import jobs as job_commands
from ..db.queries import (
    jobs as job_queries,
    processes as process_queries,
)

logger = logging.getLogger(__name__)


async def paginated_list_jobs(
    session: AsyncSession,
    user: Principal | None,
    authorizer: PottoAuthorizer,
    *,
    page: int = 1,
    page_size: int = 20,
    include_total: bool = False,
    identifiers_filter: Sequence[str] | None = None,
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
            identifiers_filter=identifiers_filter,
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
                identifiers_filter=identifiers_filter,
            )
        case _:
            accessible_job_ids = (
                await authorizer.get_accessible_private_job_identifiers(user)
            )
            accessible_process_ids = (
                await authorizer.get_accessible_process_identifiers(user)
            )
            (
                accessible_jobs,
                count,
            ) = await job_queries.paginated_list_user_jobs(
                session,
                page=page,
                page_size=page_size,
                include_total=include_total,
                user_id=user.id,
                accessible_job_identifiers=accessible_job_ids,
                accessible_process_identifiers=accessible_process_ids,
                identifiers_filter=identifiers_filter,
            )
    return [item.to_potto() for item in accessible_jobs], count


async def get_job(
    session: AsyncSession,
    user: Principal | None,
    authorizer: PottoAuthorizer,
    identifier: str,
) -> JobSchema | None:
    resource = await job_queries.get_job(session, identifier)
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
    process_identifier: str,
    to_create: JobCreate,
) -> JobSchema:
    db_process = await process_queries.get_process_by_resource_identifier(
        session, process_identifier
    )
    if db_process is None:
        raise exceptions.ResourceNotFoundError(
            f"process {process_identifier!r} does not exist."
        )
    process = db_process.to_potto()
    if not await authorizer.can_create_job(user, process):
        raise exceptions.CannotCreateResourceError(
            f"User does not have permission to create a job for process "
            f"{process_identifier!r}."
        )
    if process.deployment_status.value != ProcessDeploymentStatusValue.DEPLOYED:
        raise exceptions.CannotCreateResourceError(
            f"process {process_identifier!r} is not deployed."
        )
    # anonymous users have no identity, so their jobs are owned by the process
    # owner, and must be public in order for their creator to be able to see them
    match user:
        case PottoUser():
            owner_id = user.id
        case _:
            owner_id = process.owner.id
    try:
        created = await job_commands.create_job(
            session,
            to_create,
            process_id=cast(int, db_process.id),
            owner_id=owner_id,
            is_public=user is None,
        )
    except DatabaseError as err:
        await session.rollback()
        raise exceptions.CannotCreateResourceError(str(err)) from err
    return created.to_potto()


async def set_job_status(
    session: AsyncSession,
    user: Principal,
    authorizer: PottoAuthorizer,
    identifier: str,
    status: JobStatus,
    *,
    from_statuses: Collection[JobStatus] | None = None,
    message: str | None = None,
    progress: int | None = None,
    exception: OgcApiException | None = None,
) -> tuple[JobSchema, bool]:
    """Update a job's status, optionally only if it currently has some status.

    Returns the job, as it is after the call, and whether it was updated - which
    is False when ``from_statuses`` is given and the job had none of them.
    """
    db_job = await job_queries.get_job(session, identifier)
    if db_job is None:
        raise exceptions.ResourceNotFoundError(f"job {identifier!r} does not exist.")
    if not await authorizer.can_update_job_status(user, db_job.to_potto()):
        raise exceptions.CannotUpdateResourceError(
            f"User does not have permission to update the status of job {identifier!r}."
        )
    try:
        updated = await job_commands.set_job_status(
            session,
            identifier,
            status,
            from_statuses=from_statuses,
            message=message,
            exception=exception,
            progress=progress,
        )
    except DatabaseError as err:
        await session.rollback()
        raise exceptions.CannotUpdateResourceError(str(err)) from err
    if updated is not None:
        return updated.to_potto(), True
    session.expire_all()
    if (current := await job_queries.get_job(session, identifier)) is None:
        raise exceptions.ResourceNotFoundError(f"job {identifier!r} does not exist.")
    return current.to_potto(), False


async def delete_job(
    session: AsyncSession,
    user: Principal,
    authorizer: PottoAuthorizer,
    identifier: str,
) -> None:
    db_job = await job_queries.get_job(session, identifier)
    if db_job is None:
        raise exceptions.ResourceNotFoundError(f"job {identifier!r} does not exist.")
    if not await authorizer.can_delete_job(user, db_job.to_potto()):
        raise exceptions.CannotDeleteResourceError(
            f"User does not have permission to delete job {identifier!r}."
        )
    try:
        return await job_commands.delete_job(session, identifier)
    except DatabaseError as err:
        raise exceptions.CannotDeleteResourceError(str(err)) from err
