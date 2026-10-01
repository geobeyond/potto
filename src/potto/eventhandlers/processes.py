import asyncio
import logging
from typing import (
    Annotated,
    TYPE_CHECKING,
)

from faststream import Context
from faststream.mqtt import QoS

from ..exceptions import DeploymentAlreadyInProgressError
from ..constants import (
    LinkRelation,
    MediaType,
)
from ..pubsub.audience import resolve_process_audience
from ..pubsub.topics import (
    is_valid_topic_user_id,
    private_process_topic,
    public_process_topic,
)
from ..schemas.auth import SystemPrincipal
from ..schemas.events import (
    AnyInternalProcessEvent,
    ExternalEventLink,
    ExternalProcessEvent,
    ExternalProcessEventType,
    ExternalPublishers,
    InternalProcessDeletionEvent,
)
from ..schemas.processes import (
    ProcessDeploymentStatusValue,
)
from ..wrapper import Potto

if TYPE_CHECKING:
    from ..config import PottoSettings

logger = logging.getLogger(__name__)

_BRIDGE_PRINCIPAL = SystemPrincipal("public-bridge")


async def handle_internal_process_event(
    event: AnyInternalProcessEvent,
    settings: Annotated["PottoSettings", Context()],
    external_publishers: Annotated[ExternalPublishers, Context()],
) -> None:
    """Handle a process event: reconcile the process and bridge the event.

    Both are done concurrently, so that a long-running deployment does not delay
    notifying the event, and independently, so that a failure in one does not
    prevent the other.
    """
    steps = {
        "reconciling the process": internal_handle_process_event(event, settings),
        "bridging the event to the public broker": bridge_internal_event_to_public(
            event, settings, external_publishers
        ),
    }
    results = await asyncio.gather(*steps.values(), return_exceptions=True)
    for description, result in zip(steps, results, strict=True):
        if isinstance(result, Exception):
            logger.error(
                f"{description} failed for the {event.event_type.value!r} event of "
                f"process {event.process_identifier!r}",
                exc_info=result,
            )
        elif isinstance(result, BaseException):
            raise result


async def bridge_internal_event_to_public(
    event: AnyInternalProcessEvent,
    settings: Annotated["PottoSettings", Context()],
    external_publishers: Annotated[ExternalPublishers, Context()],
) -> None:
    """Republish a process event to the external broker, once per audience topic."""
    logger.debug(f"received event {event=}")
    try:
        external_event_type = ExternalProcessEventType(event.event_type.value)
    except ValueError:
        return

    if isinstance(event, InternalProcessDeletionEvent):
        # since process is already gone, its audience travels with the event
        audience = event.audience
    elif (
        process := await settings.get_process_manager().get_process(
            event.process_identifier, _BRIDGE_PRINCIPAL
        )
    ) is not None:
        audience = await resolve_process_audience(process, settings)
    else:
        logger.debug(
            f"Process {event.process_identifier!r} not found, not publishing "
            f"its {event.event_type.value!r} event"
        )
        return

    external_event = ExternalProcessEvent(
        event_type=external_event_type,
        process_identifier=event.process_identifier,
        timestamp=event.timestamp,
        links=(
            [
                ExternalEventLink(
                    href=f"{settings.public_url}/api/processes/{event.process_identifier}",
                    rel=LinkRelation.SELF.value,
                    type=MediaType.JSON.value,
                )
            ]
            if external_event_type != ExternalProcessEventType.DELETED
            else []
        ),
    )
    if audience.is_public:
        await external_publishers.public_processes.publish(
            external_event,
            topic=public_process_topic(
                event.process_identifier, external_event_type.value
            ),
            qos=QoS.AT_LEAST_ONCE,
            correlation_id=event.correlation_id,
        )
        return
    for user_id in audience.user_ids:
        if not is_valid_topic_user_id(user_id):
            logger.warning(
                f"User id {user_id!r} cannot be used in a topic, not publishing "
                f"event for process {event.process_identifier!r} to it"
            )
            continue
        await external_publishers.private_processes.publish(
            external_event,
            topic=private_process_topic(
                user_id, event.process_identifier, external_event_type.value
            ),
            qos=QoS.AT_LEAST_ONCE,
            correlation_id=event.correlation_id,
        )


async def internal_handle_process_event(
    event: AnyInternalProcessEvent, settings: Annotated["PottoSettings", Context()]
) -> None:
    """Handles a process-related event"""
    logger.debug(f"received event {event=}")
    if isinstance(event, InternalProcessDeletionEvent):
        await Potto(settings).undeploy_process(
            event.process,
            user=SystemPrincipal("process-undeployer"),
            correlation_id=event.correlation_id,
        )
        return None
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
        # the process has been deleted meanwhile - undeploying it is taken care of
        # when handling its deletion event
        return None

    desired = process.get_deployment_hash()
    if (
        process.deployment_status.definition_hash == desired
        and process.deployment_status.value
        in (ProcessDeploymentStatusValue.DEPLOYED, ProcessDeploymentStatusValue.FAILED)
    ):
        return None  # already converged, nothing to do

    try:
        await potto.deploy_process(
            identifier, user=principal, correlation_id=correlation_id
        )
    except DeploymentAlreadyInProgressError:
        # whoever is deploying the process publishes an event when done, which
        # triggers reconciling it again
        logger.debug(f"process {identifier!r} is already being deployed")
