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
        Job,
        JobCreate,
        JobFilter,
        JobManagerCapabilities,
    )
    from ..schemas.processes import (
        Process,
        ProcessDeploymentStatus,
    )


class JobManagerProtocol(Protocol):
    """A protocol for potto job managers."""

    @property
    def supported_deployment_types(self) -> tuple[Literal["cwl", "oci"] | str, ...]:
        """Report which deployment types are supported by the manager."""

    async def check_health(self) -> Literal["ok", "not-ready", "error"]:
        """Check whether the manager is healthy."""

    @property
    def potto_cli_group(self) -> str:
        """The name this manager's CLI commands are grouped under (``potto <name> ...``)."""

    async def get_cli_group(self) -> "cyclopts.App | None":
        """Return a cyclopts app of this manager's own CLI commands, or None if it has none."""

    async def get_job_admin_view(self) -> "BaseModelView | None":
        """Return a starlette_admin view suitable for use in potto's admin ui."""

    async def get_job_capabilities(self) -> "JobManagerCapabilities":
        """Return the manager's capabilities."""

    async def deploy_process(self, process: "Process") -> "ProcessDeploymentStatus":
        """Deploy a process.

        This is a potentially long-running task and should thus be called from a background worker.

        Raise DeploymentFailedException when the deployment cannot be done or fails.
        """
        ...

    async def undeploy_process(self, process: "Process") -> "ProcessDeploymentStatus":
        """Undeploy a process.

        This is a potentially long-running task and should thus be called
        from a background worker.

        Raise DeploymentFailedException when the deployment cannot be done or fails.
        """
        ...

    async def get_job(
        self,
        identifier: str,
        user: "PottoUser | None",
    ) -> "Job | None":
        """Retrieve a job."""

    async def paginated_list_jobs(
        self,
        user: "PottoUser | None",
        *,
        page: int = 1,
        page_size: int = 20,
        include_total: bool = False,
        filter_: "JobFilter | None" = None,
    ) -> tuple[list["Job"], int | None]:
        """Retrieve a list of jobs"""

    async def create_job(
        self,
        to_create: "JobCreate",
        user: "PottoUser",
    ) -> "Job":
        """Create a new job. This implicitly means that execution is also scheduled to start."""

    async def delete_job(
        self,
        identifier: str,
        user: "PottoUser",
    ) -> None:
        """Delete a job.

        When the manager does not support deleting jobs this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """


JobManagerFactoryProtocol: TypeAlias = Callable[
    [dict[str, Any], "PottoSettings"],
    JobManagerProtocol,
]
