import logging
from typing import (
    Annotated,
    TYPE_CHECKING,
)

from faststream import Context

from ..schemas.auth import SystemPrincipal
from ..schemas.events import InternalJobEvent
from ..wrapper import Potto

if TYPE_CHECKING:
    from ..config import PottoSettings

logger = logging.getLogger(__name__)

_EXECUTOR_PRINCIPAL = SystemPrincipal("job-executor")


async def internal_handle_job_created(
    event: InternalJobEvent, settings: Annotated["PottoSettings", Context()]
) -> None:
    """Execute a newly created job."""
    logger.debug(f"received event {event=}")
    await Potto(settings).execute_job(
        event.job_identifier,
        user=_EXECUTOR_PRINCIPAL,
        correlation_id=event.correlation_id,
    )
