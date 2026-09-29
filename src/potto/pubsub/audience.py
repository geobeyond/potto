"""Resolution of which users get notified about events on a resource."""

import asyncio
from typing import TYPE_CHECKING

from ..schemas.auth import SystemPrincipal
from ..schemas.events import ResourceAudience

if TYPE_CHECKING:
    from ..config import PottoSettings
    from ..schemas.processes import Process

_PRINCIPAL = SystemPrincipal("pubsub-audience-resolver")


async def resolve_process_audience(
    process: "Process", settings: "PottoSettings"
) -> ResourceAudience:
    """Resolve the audience for events on a process.

    A public process can be viewed by everyone. For a private process, the
    candidates are its owner and the users it has been shared with (editors and
    viewers), and potto's authorizer decides which of them are allowed to view
    it - this way the audience follows whichever authorization backend is
    configured.
    """
    if process.is_public:
        return ResourceAudience(is_public=True)
    user_account_manager = settings.get_user_account_manager()
    editors = await user_account_manager.list_resource_editors(
        "process", process.identifier, _PRINCIPAL
    )
    viewers = await user_account_manager.list_resource_viewers(
        "process", process.identifier, _PRINCIPAL
    )
    candidates = {
        user.id: user for user in (process.owner, *editors, *viewers) if user.is_active
    }
    authorizer = settings.get_authorizer()
    allowed = await asyncio.gather(
        *(authorizer.can_view_process(user, process) for user in candidates.values())
    )
    return ResourceAudience(
        is_public=False,
        user_ids=sorted(
            user_id
            for user_id, is_allowed in zip(candidates, allowed, strict=True)
            if is_allowed
        ),
    )
