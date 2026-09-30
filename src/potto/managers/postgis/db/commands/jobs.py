import datetime as dt
import logging
from typing import cast

from sqlmodel.ext.asyncio.session import AsyncSession

from .....exceptions import (
    CannotCreateResourceError,
    CannotUpdateResourceError,
    ResourceNotFoundError,
)
from .....schemas.jobs import (
    JobCreate,
    JobStatus,
)
from ..models import Job
from ..queries.jobs import get_job

logger = logging.getLogger(__name__)


async def create_job(session: AsyncSession, to_create: JobCreate) -> Job:
    logger.debug(f"{to_create=}")
    instance = Job.model_validate(to_create, from_attributes=True)
    session.add(instance)
    await session.commit()
    await session.refresh(instance)
    if (created := await get_job(session, cast(int, instance.id))) is None:
        raise CannotCreateResourceError("error creating job")
    return created


async def delete_job(
    session: AsyncSession,
    job_id: int,
) -> None:
    if instance := (await get_job(session, job_id)):
        await session.delete(instance)
        await session.commit()
    else:
        raise ResourceNotFoundError(f"Job with id {job_id} does not exist.")


async def set_job_status(
    session: AsyncSession,
    db_job: Job,
    status: JobStatus,
    message: str | None = None,
    exception: dict | None = None,
    progress: int | None = None
) -> Job:
    now_ = dt.datetime.now(dt.UTC)
    db_job.updated_at = now_
    previous_status = db_job.status
    just_started = (
            previous_status == JobStatus.ACCEPTED and status == JobStatus.RUNNING
    )
    if just_started:
        db_job.started_at = now_
    elif status in (
        JobStatus.SUCCESSFUL,
        JobStatus.FAILED
    ):
        db_job.finished_at = now_

    if message is not None:
        db_job.message = message
    if progress is not None:
        db_job.progress = max(min(progress, 100), 0)
    if exception is not None:
        db_job.exception = exception
    session.add(db_job)
    await session.commit()
    await session.refresh(db_job)

    if (updated := await get_job(session, cast(int, db_job.id))) is None:
        raise CannotUpdateResourceError(f"error setting job status {db_job.id}")
    return updated
