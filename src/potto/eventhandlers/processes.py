import logging
from typing import (
    Annotated,
    TYPE_CHECKING,
)

from faststream import Context

from ..constants import (
    PROCESS_EXTERNAL_PRIVATE_TOPIC_PREFIX,
    PROCESS_EXTERNAL_PUBLIC_TOPIC_PREFIX,
)
from ..schemas.auth import SystemPrincipal
from ..schemas.events import (
    ExternalPublishers,
    InternalProcessEvent,
    InternalProcessEventType,
    ExternalPublicProcessEvent,
    ExternalPrivateProcessEvent,
    ExternalProcessEventType,
)
from ..schemas.processes import (
    ProcessDeploymentStatusValue,
)
from ..wrapper import Potto

if TYPE_CHECKING:
    from ..config import PottoSettings

logger = logging.getLogger(__name__)


async def bridge_internal_event_to_public(
        event: InternalProcessEvent,
        settings: Annotated["PottoSettings", Context()],
        external_publishers: Annotated[ExternalPublishers, Context()],
):
    logger.debug(f"received event {event=}")

    process_manager = settings.get_process_manager()
    if (
            process := await process_manager.get_process(
                event.process_identifier, event.initiated_by)
    ) is None:
        logger.debug(f"process {event.process_identifier} not found")
        return

    if event.event_type not in (
            InternalProcessEventType.CREATED,
            InternalProcessEventType.DELETED,
            InternalProcessEventType.UPDATED,
            InternalProcessEventType.DEPLOYED,
            InternalProcessEventType.UNDEPLOYED,

    ):
        return

    if process.is_public:
        await external_publishers.public_processes.publish(
            ExternalPublicProcessEvent(
                event_type=ExternalProcessEventType(event.event_type.value),
                process_identifier=event.process_identifier,
                timestamp=event.timestamp,
            ),
            topic="/".join(
                (
                    PROCESS_EXTERNAL_PUBLIC_TOPIC_PREFIX,
                    event.process_identifier,
                    event.event_type.value,
                )
            )
        )
    else:
        await external_publishers.private_processes.publish(
            ExternalPrivateProcessEvent(
                event_type=ExternalProcessEventType(event.event_type.value),
                process_identifier=event.process_identifier,
                timestamp=event.timestamp,
            ),
            topic="/".join(
                (
                    PROCESS_EXTERNAL_PRIVATE_TOPIC_PREFIX.format(user_id=event.initiated_by.identifier),
                    event.process_identifier,
                    event.event_type.value,
                )
            )
        )


async def internal_handle_process_event(
    event: InternalProcessEvent, settings: Annotated["PottoSettings", Context()]
) -> None:
    """Handles a process-related event"""
    logger.debug(f"received event {event=}")
    await _reconcile_process(
        event.process_identifier, event.correlation_id, settings=settings
    )


async def _reconcile_process(
    identifier: str, correlation_id: str, *, settings: "PottoSettings"
) -> None:
    potto = Potto(settings)
    principal = SystemPrincipal("process-reconciler")
    process = await potto.get_process(identifier, user=principal)

    if process is None:
        # ensure there is no deployment leftover for the process - not sure how yet
        await potto.undeploy_process(
            identifier, user=principal, correlation_id=correlation_id
        )
        return None

    desired = process.get_deployment_hash()
    if (
        process.deployment_status.definition_hash == desired
        and process.deployment_status.value
        in (ProcessDeploymentStatusValue.DEPLOYED, ProcessDeploymentStatusValue.FAILED)
    ):
        return None  # already converged, nothing to do

    await potto.deploy_process(
        identifier, user=principal, correlation_id=correlation_id
    )
