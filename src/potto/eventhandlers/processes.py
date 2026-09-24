import logging
from typing import (
    Annotated,
    TYPE_CHECKING,
)

from faststream import Context

from ..authz.authorizer import SystemPrincipal
from ..schemas.processes import (
    ProcessEvent,
    ProcessDeploymentStatusValue,
)
from ..wrapper import Potto

if TYPE_CHECKING:
    from ..config import PottoSettings

logger = logging.getLogger(__name__)


async def handle_process_event(
    event: ProcessEvent, settings: Annotated["PottoSettings", Context()]
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
