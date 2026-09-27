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
    from ..schemas.jobs import (
        JobResult,
        JobResultFilter,
        JobResultManagerCapabilities,
    )


class JobResultManagerProtocol(Protocol):
    """A protocol for potto job result managers."""

    async def check_health(self) -> Literal["ok", "not-ready", "error"]:
        """Check whether the manager is healthy."""

    @property
    def potto_cli_group(self) -> str:
        """The name this manager's CLI commands are grouped under (``potto <name> ...``)."""

    async def get_cli_group(self) -> "cyclopts.App | None":
        """Return a cyclopts app of this manager's own CLI commands, or None if it has none."""

    async def get_job_result_admin_view(self) -> "BaseModelView | None":
        """Return a starlette_admin view suitable for use in potto's admin ui."""

    async def get_job_result_capabilities(self) -> "JobResultManagerCapabilities":
        """Return the manager's capabilities."""

    async def get_job_result(
        self,
        job_identifier: str,
        identifier: str,
        user: "PottoUser | None",
    ) -> "JobResult | None":
        """Retrieve a job result."""

    async def paginated_list_job_results(
        self,
        job_identifier: str,
        user: "PottoUser | None",
        *,
        page: int = 1,
        page_size: int = 20,
        include_total: bool = False,
        filter_: "JobResultFilter | None" = None,
    ) -> tuple[list["JobResult"], int | None]:
        """Retrieve a list of job results"""

    async def delete_job_result(
        self,
        job_identifier: str,
        identifier: str,
        user: "PottoUser",
    ) -> None:
        """Delete a job result.

        When the manager does not support deleting jobs this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """


JobResultManagerFactoryProtocol: TypeAlias = Callable[
    [dict[str, Any], "PottoSettings"],
    JobResultManagerProtocol,
]
