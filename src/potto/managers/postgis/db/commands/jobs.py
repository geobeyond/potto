import dataclasses
import logging
from typing import Collection

from sqlmodel import (
    func,
    update,
)
from sqlmodel.ext.asyncio.session import AsyncSession

from .....exceptions import (
    CannotCreateResourceError,
    ResourceNotFoundError,
)
from .....schemas.base import OgcApiException
from .....schemas.jobs import (
    JobCreate,
    JobStatus,
)
from ..models import Job
from ..queries.jobs import get_job

logger = logging.getLogger(__name__)


async def create_job(
    session: AsyncSession,
    to_create: JobCreate,
    *,
    process_id: int,
    owner_id: str,
    is_public: bool,
) -> Job:
    logger.debug(f"{to_create=}")
    instance = Job(
        process_id=process_id,
        owner_id=owner_id,
        is_public=is_public,
        status=JobStatus.ACCEPTED,
        processing_entity_type="ogc-api-processes",
        response_type=to_create.response,
        inputs=to_create.inputs,
        outputs={
            name: {
                "format_": output.format_,
                "transmission_mode": output.transmission_mode,
            }
            for name, output in to_create.outputs.items()
        },
        callback_uris=(
            {
                "success_uri": to_create.subscriber.success_uri,
                "in_progress_uri": to_create.subscriber.in_progress_uri,
                "failed_uri": to_create.subscriber.failed_uri,
            }
            if to_create.subscriber is not None
            else None
        ),
    )
    session.add(instance)
    await session.commit()
    await session.refresh(instance)
    if (created := await get_job(session, instance.resource_identifier)) is None:
        raise CannotCreateResourceError("error creating job")
    return created


async def delete_job(
    session: AsyncSession,
    identifier: str,
) -> None:
    if instance := (await get_job(session, identifier)):
        await session.delete(instance)
        await session.commit()
    else:
        raise ResourceNotFoundError(f"Job {identifier!r} does not exist.")


async def set_job_status(
    session: AsyncSession,
    identifier: str,
    status: JobStatus,
    *,
    from_statuses: Collection[JobStatus] | None = None,
    message: str | None = None,
    exception: OgcApiException | None = None,
    progress: int | None = None,
) -> Job | None:
    """Update a job's status, optionally only if it currently has some status.

    The check and the update are a single conditional ``UPDATE`` statement, so
    that concurrent callers cannot both succeed in making the same transition -
    e.g. ``from_statuses={JobStatus.ACCEPTED}`` lets only one of several workers
    claim a job for execution.

    Returns None when the job does not exist or, if ``from_statuses`` is given,
    when it does not currently have any of them.
    """
    values: dict = {"status": status}
    if status == JobStatus.RUNNING:
        values["started_at"] = func.coalesce(Job.started_at, func.now())
    elif status in (
        JobStatus.SUCCESSFUL,
        JobStatus.FAILED,
        JobStatus.DISMISSED,
    ):
        values["finished_at"] = func.now()
    if message is not None:
        values["message"] = message
    if progress is not None:
        values["progress"] = max(min(progress, 100), 0)
    if exception is not None:
        values["exception"] = dataclasses.asdict(exception)
    statement = update(Job).where(
        Job.resource_identifier == identifier  # ty: ignore[invalid-argument-type]
    )
    if from_statuses is not None:
        statement = statement.where(
            Job.status.in_(from_statuses)  # ty: ignore[unresolved-attribute]
        )
    statement = statement.values(**values).returning(Job.id)  # ty: ignore[no-matching-overload]
    updated_id = (await session.exec(statement)).scalar_one_or_none()
    await session.commit()
    if updated_id is None:
        return None
    # the update bypasses the ORM, so any instance of this job already loaded
    # in the session is now stale
    session.expire_all()
    return await get_job(session, identifier)
