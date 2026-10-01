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

    from ..authz.authorizer import Principal
    from ..config import PottoSettings
    from ..schemas.jobs import (
        Job,
        JobCreate,
        JobFilter,
        JobManagerCapabilities,
        JobStatus,
    )
    from ..schemas.base import OgcApiException
    from ..schemas.processes import (
        Process,
        ProcessDeploymentStatus,
    )


class JobManagerProtocol(Protocol):
    """A protocol for potto job managers."""

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

    @property
    def supported_deployment_types(self) -> tuple[Literal["cwl", "oci"] | str, ...]:
        """Report which deployment types are supported by the manager."""

    async def deploy_process(self, process: "Process") -> "ProcessDeploymentStatus":
        """Deploy a process.

        This is a potential long-running task and should thus be called from a background worker.

        Raise DeploymentFailedException when the deployment cannot be done or fails.
        """

    async def undeploy_process(self, process: "Process") -> "ProcessDeploymentStatus":
        """Undeploy a process.

        This is a potential long-running task and should thus be called
        from a background worker.

        Raise DeploymentFailedException when the deployment cannot be done or fails.
        """

    async def get_job(
        self,
        identifier: str,
        user: "Principal | None",
    ) -> "Job | None":
        """Retrieve a job."""

    async def paginated_list_jobs(
        self,
        user: "Principal | None",
        *,
        page: int = 1,
        page_size: int = 20,
        include_total: bool = False,
        filter_: "JobFilter | None" = None,
    ) -> tuple[list["Job"], int | None]:
        """Retrieve a list of jobs"""

    async def create_job(
        self,
        process_identifier: str,
        to_create: "JobCreate",
        user: "Principal | None",
    ) -> "Job":
        """Create a new job for the process.

        Implementations should make this method return fast, possibly
        deferring execution to when the ``execute_job()`` method is called. The
        suggested workflow is something like this:

        - potto wrapper calls ``manager.create_job()`` and immediately gets a
          job object back with a suitable status to let the caller know whether
          the job was accepted or rejected
        - potto wrapper emits an internal 'job created' event
        - upon handling the event, the potto background worker eventually calls
          ``manager.execute_job()``, where job execution is then free to
           occur and to take as long as it needs to.

        Implementations are also free to implement ``create_job()`` in a way
        that it already starts job execution using some other form of
        background processing, just as long as ``create_job()`` returns fast.
        ``execute_job()`` is still called by the potto background worker, in
        which case, it could be a no-op.
        """

    async def execute_job(
        self,
        identifier: str,
        user: "Principal",
    ) -> "Job":
        """Start executing a previously created job.

        This is called by potto's background worker after a job has been created.
        It may return before the job's execution finishes - for example, a manager
        that delegates execution to an external system will just submit the job
        there and return, whereas a manager that runs jobs itself may run them to
        completion. Either way, job status changes are to be recorded with
        ``set_job_status()``.

        Since potto's internal events are delivered at least once, this may be
        called more than once for the same job. Implementations must only start
        executing a job that is still ``accepted``, and otherwise return the job
        as-is.
        """

    async def set_job_status(
        self,
        identifier: str,
        status: "JobStatus",
        user: "Principal",
        *,
        message: str | None = None,
        progress: int | None = None,
        exception: "OgcApiException | None" = None,
    ) -> "Job":
        """Update a job's status."""

    async def delete_job(
        self,
        identifier: str,
        user: "Principal",
    ) -> None:
        """Delete a job.

        When the manager does not support deleting jobs this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """


JobManagerFactoryProtocol: TypeAlias = Callable[
    [dict[str, Any], "PottoSettings"],
    JobManagerProtocol,
]
