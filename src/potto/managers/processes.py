from typing import (
    Any,
    Callable,
    Literal,
    Protocol,
    TypeAlias,
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    import cyclopts
    from starlette_admin.views import BaseModelView

    from ..config import PottoSettings
    from ..schemas.auth import PottoUser
    from ..schemas.processes import (
        Process,
        ProcessCreate,
        ProcessFilter,
        ProcessManagerCapabilities,
        ProcessUpdate,
    )


class ProcessManagerProtocol(Protocol):
    """A protocol for potto process managers."""

    async def check_health(self) -> Literal["ok", "not-ready", "error"]:
        """Check whether the manager is healthy."""

    @property
    def potto_cli_group(self) -> str:
        """The name this manager's CLI commands are grouped under (``potto <name> ...``)."""

    async def get_cli_group(self) -> "cyclopts.App | None":
        """Return a cyclopts app of this manager's own CLI commands, or None if it has none."""

    async def get_process_admin_view(self) -> "BaseModelView | None":
        """Return a starlette_admin view suitable for use in potto's admin ui."""

    async def get_process_capabilities(self) -> "ProcessManagerCapabilities":
        """Return the manager's capabilities."""

    async def get_process(
        self,
        identifier: str,
        user: "PottoUser | None",
    ) -> "Process | None":
        """Retrieve a process."""

    async def paginated_list_processes(
        self,
        user: "PottoUser | None",
        *,
        page: int = 1,
        page_size: int = 20,
        include_total: bool = False,
        filter_: "ProcessFilter | None" = None,
    ) -> tuple[list["Process"], int | None]:
        """Retrieve a list of processes"""

    async def create_process(
        self,
        to_create: "ProcessCreate",
        user: "PottoUser",
    ) -> "Process":
        """Create a new process.

        When the manager does not support creating processes this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """

    async def update_process(
        self,
        process: "Process",
        to_update: "ProcessUpdate",
        user: "PottoUser",
    ) -> "Process":
        """Update an existing process.

        When the manager does not support updating processes this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """

    async def delete_process(
        self,
        identifier: str,
        user: "PottoUser",
    ) -> None:
        """Delete a process.

        When the manager does not support deleting processes this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """

    async def grant_process_access(
        self,
        *,
        granting_user: "PottoUser",
        target_user_id: str,
        process: "Process",
        role: str,
    ) -> None:
        """Grant a role on the input process to the target user.

        When the manager does not support granting process access this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """

    async def revoke_process_access(
        self,
        *,
        revoking_user: "PottoUser",
        target_user_id: str,
        process: "Process",
    ) -> None:
        """Revoke a user's access to a process.

        When the manager does not support revoking process access this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """


ProcessManagerFactoryProtocol: TypeAlias = Callable[
    [dict[str, Any], "PottoSettings"],
    ProcessManagerProtocol,
]
