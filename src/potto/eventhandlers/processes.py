import logging
from typing import Annotated

from faststream import Path

from ..schemas.processes import (
    ProcessCreatedEvent,
    ProcessUpdatedEvent,
    ProcessDeletedEvent,
)

logger = logging.getLogger(__name__)


async def handle_process_created(
    identifier: Annotated[str, Path()], event: ProcessCreatedEvent
):
    logger.debug(f"{identifier=} received event {event=}")


async def handle_process_updated(
    identifier: Annotated[str, Path()],
    event: ProcessUpdatedEvent,
):
    logger.debug(f"{identifier=} received event {event=}")


async def handle_process_deleted(
    identifier: Annotated[str, Path()],
    event: ProcessDeletedEvent,
):
    logger.debug(f"{identifier=} received event {event=}")
