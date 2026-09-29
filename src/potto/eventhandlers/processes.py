import logging
from typing import (
    Annotated,
    TYPE_CHECKING,
)

from faststream import Context
from faststream.mqtt import QoS

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
