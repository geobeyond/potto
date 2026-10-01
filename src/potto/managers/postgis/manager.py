import asyncio
import json
import logging
from typing import (
    Any,
    Callable,
    Collection,
    TypeVar,
    cast,
    Literal,
    TYPE_CHECKING,
)

import alembic.config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
import cyclopts
import docker
import docker.errors
from sqlalchemy import create_engine
from starlette_admin.views import BaseModelView

from ...authz.authorizer import (
    PottoAuthorizer,
    Principal,
)
from ... import exceptions
from ...schemas.base import OgcApiException
from ...schemas import (
    auth as auth_schemas,
    collections as collection_schemas,
    jobs as job_schemas,
    metadata as metadata_schemas,
    processes as process_schemas,
)

from .admin.collections import CollectionView
from .admin.metadata import ServerMetadataModelView
from .admin.processes import ProcessView
from .admin.users import UserView
from .cli import build_cli_group
from .config import PostgisManagerConfiguration
from .db.alembic_utils import build_alembic_config
from . import oci
from .operations import (
    collections as collection_ops,
    jobs as job_ops,
    metadata as metadata_ops,
    processes as process_ops,
    users as user_ops,
)

if TYPE_CHECKING:
    from ...config import PottoSettings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class PostgisManager:
    """A potto manager backed by a PostGIS DB.

    This implements the following potto manager protocols:

    - ``CollectionManagerProtocol``,
    - ``JobManagerProtocol``,
    - ``ProcessManagerProtocol``,
    - ``ServerMetadataProtocol``,
    - ``UserAccountProtocol``
    """

    authorizer: PottoAuthorizer
    config: PostgisManagerConfiguration
    settings: "PottoSettings"

    def __init__(self, config: PostgisManagerConfiguration, settings: "PottoSettings"):
        self.authorizer = settings.get_authorizer()
        self.config = config
        self.settings = settings

    async def check_health(self) -> Literal["ok", "not-ready", "error"]:
        """Check whether the manager is healthy."""
        return await _check_health(
            build_alembic_config(self.config.database_dsn.unicode_string())
        )

    @property
    def potto_cli_group(self) -> str:
        return "postgis-manager"

    async def get_cli_group(self) -> "cyclopts.App | None":
        return build_cli_group(self)

    async def get_collection_admin_view(self) -> "BaseModelView | None":
        return CollectionView()

    async def get_collection_capabilities(
        self,
    ) -> collection_schemas.CollectionManagerCapabilities:
        return collection_schemas.CollectionManagerCapabilities(
            supports_creation=True,
            supports_modification=True,
            supports_deletion=True,
            supports_granting_access=True,
            supports_revoking_access=True,
        )

    async def get_collection(
        self,
        identifier: str,
        user: Principal | None,
    ) -> collection_schemas.Collection | None:
        """Retrieve a collection."""
        async with self.config.get_db_session_maker()() as db_session:
            return await collection_ops.get_collection_by_resource_identifier(
                db_session, user, self.authorizer, identifier
            )

    async def paginated_list_collections(
        self,
        user: Principal | None,
        *,
        page: int = 1,
        page_size: int = 20,
        include_total: bool = False,
        filter_: collection_schemas.CollectionFilter | None = None,
    ) -> tuple[list[collection_schemas.Collection], int | None]:
        """Retrieve a list of collections"""
        async with self.config.get_db_session_maker()() as db_session:
            return await collection_ops.paginated_list_collections(
                db_session,
                user,
                self.authorizer,
                page=page,
                page_size=page_size,
                include_total=include_total,
                identifier_filter=(
                    filter_.identifiers[0]
                    if filter_ is not None and filter_.identifiers
                    else None
                ),
                collection_type_filter=(
                    [filter_.type_] if filter_ is not None and filter_.type_ else None
                ),
                spatial_intersect=(
                    filter_.spatial_intersect if filter_ is not None else None
                ),
            )

    async def create_collection(
        self,
        to_create: collection_schemas.CollectionCreate,
        user: Principal,
    ) -> collection_schemas.Collection:
        """Create a new collection."""
        async with self.config.get_db_session_maker()() as db_session:
            return await collection_ops.create_collection(
                db_session, user, self.authorizer, to_create, self.settings
            )

    async def update_collection(
        self,
        collection: collection_schemas.Collection,
        to_update: collection_schemas.CollectionUpdate,
        user: Principal,
    ) -> collection_schemas.Collection:
        """Update an existing collection."""
        async with self.config.get_db_session_maker()() as db_session:
            return await collection_ops.update_collection(
                db_session, user, self.authorizer, collection, to_update
            )

    async def delete_collection(
        self,
        identifier: str,
        user: Principal,
    ) -> None:
        """Delete a collection."""
        async with self.config.get_db_session_maker()() as db_session:
            return await collection_ops.delete_collection(
                db_session, user, self.authorizer, identifier
            )

    async def grant_collection_access(
        self,
        *,
        granting_user: Principal,
        target_user_id: str,
        collection: collection_schemas.Collection,
        role: str,
    ) -> None:
        """Grant a role on the input collection to the target user."""
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.grant_collection_access(
                db_session,
                granting_user,
                self.authorizer,
                target_user_id,
                collection,
                role,
            )

    async def revoke_collection_access(
        self,
        *,
        revoking_user: Principal,
        target_user_id: str,
        collection: collection_schemas.Collection,
    ) -> None:
        """Revoke a user's access to a collection."""
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.revoke_collection_access(
                db_session,
                revoking_user,
                self.authorizer,
                target_user_id,
                collection,
            )

    async def get_server_metadata_admin_view(self) -> "BaseModelView | None":
        return ServerMetadataModelView()

    async def get_server_metadata_capabilities(
        self,
    ) -> metadata_schemas.ServerMetadataManagerCapabilities:
        return metadata_schemas.ServerMetadataManagerCapabilities(
            supports_modification=True
        )

    async def get_server_metadata(self) -> metadata_schemas.ServerMetadata:
        async with self.config.get_db_session_maker()() as db_session:
            return await metadata_ops.get_server_metadata(db_session)

    async def update_server_metadata(
        self,
        to_update: metadata_schemas.ServerMetadataUpdate,
        user: Principal | None,
    ) -> metadata_schemas.ServerMetadata:
        async with self.config.get_db_session_maker()() as db_session:
            return await metadata_ops.update_server_metadata(
                db_session,
                user,
                self.authorizer,
                to_update,
            )

    async def get_user_account_admin_view(self) -> "BaseModelView | None":
        return UserView()

    async def get_user_account_capabilities(
        self,
    ) -> auth_schemas.UserAccountManagerCapabilities:
        return auth_schemas.UserAccountManagerCapabilities(
            supports_creation=True,
            supports_modification=True,
            supports_deletion=True,
        )

    async def get_user(
        self,
        user_id: str,
        requesting_user: Principal | None,
    ) -> auth_schemas.PottoUser | None:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.get_user(
                db_session, requesting_user, self.authorizer, user_id
            )

    async def get_user_by_username(
        self,
        username: str,
        requesting_user: Principal | None,
    ) -> auth_schemas.PottoUser | None:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.get_user_by_username(
                db_session, requesting_user, self.authorizer, username
            )

    async def paginated_list_users(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        include_total: bool = False,
        filter_: auth_schemas.UserFilter | None = None,
        requesting_user: Principal | None,
    ) -> tuple[list[auth_schemas.PottoUser], int | None]:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.paginated_list_users(
                db_session,
                requesting_user,
                self.authorizer,
                username_filter=filter_.username if filter_ else None,
                admin_filter=bool(filter_ and filter_.is_admin),
                page=page,
                page_size=page_size,
                include_total=include_total,
            )

    async def create_user(
        self,
        to_create: auth_schemas.UserCreate,
        requesting_user: Principal | None,
    ) -> auth_schemas.PottoUser:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.create_user(
                db_session,
                requesting_user,
                self.authorizer,
                to_create,
            )

    async def update_user(
        self,
        user_id: str,
        to_update: auth_schemas.UserUpdate,
        requesting_user: Principal | None,
    ) -> auth_schemas.PottoUser:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.update_user(
                db_session,
                requesting_user,
                self.authorizer,
                user_id,
                to_update,
            )

    async def delete_user(
        self,
        user_id: str,
        requesting_user: Principal | None,
    ) -> None:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.delete_user(
                db_session, requesting_user, self.authorizer, user_id
            )

    async def provision_oidc_user(
        self, to_create: auth_schemas.UserCreateFromOidc
    ) -> auth_schemas.PottoUser:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.provision_oidc_user(db_session, to_create)

    async def authenticate(
        self, username: str, password: str
    ) -> auth_schemas.PottoUser | None:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.authenticate(db_session, username, password)

    async def list_resource_editors(
        self,
        resource_type: str,
        resource_identifier: str,
        requesting_user: Principal | None,
    ) -> list[auth_schemas.PottoUser]:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.list_resource_editors(
                db_session,
                requesting_user,
                self.authorizer,
                resource_type,
                resource_identifier,
            )

    async def list_resource_viewers(
        self,
        resource_type: str,
        resource_identifier: str,
        requesting_user: Principal | None,
    ) -> list[auth_schemas.PottoUser]:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.list_resource_viewers(
                db_session,
                requesting_user,
                self.authorizer,
                resource_type,
                resource_identifier,
            )

    async def get_process_admin_view(self) -> "BaseModelView | None":
        return ProcessView()

    async def get_process_capabilities(
        self,
    ) -> process_schemas.ProcessManagerCapabilities:
        return process_schemas.ProcessManagerCapabilities(
            supports_creation=True,
            supports_modification=True,
            supports_deletion=True,
            supports_granting_access=True,
            supports_revoking_access=True,
        )

    async def get_process(
        self,
        identifier: str,
        user: Principal | None,
    ) -> process_schemas.Process | None:
        """Retrieve a process."""
        async with self.config.get_db_session_maker()() as db_session:
            return await process_ops.get_process_by_resource_identifier(
                db_session, user, self.authorizer, identifier
            )

    async def paginated_list_processes(
        self,
        user: Principal | None,
        *,
        page: int = 1,
        page_size: int = 20,
        include_total: bool = False,
        filter_: process_schemas.ProcessFilter | None = None,
    ) -> tuple[list[process_schemas.Process], int | None]:
        """Retrieve a list of processes."""
        async with self.config.get_db_session_maker()() as db_session:
            return await process_ops.paginated_list_processes(
                db_session,
                user,
                self.authorizer,
                page=page,
                page_size=page_size,
                include_total=include_total,
                identifier_filter=(
                    filter_.identifiers[0]
                    if filter_ is not None and filter_.identifiers
                    else None
                ),
            )

    async def create_process(
        self,
        to_create: process_schemas.ProcessCreate,
        user: Principal,
    ) -> process_schemas.Process:
        """Create a new process.

        When the manager does not support creating processes this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """
        async with self.config.get_db_session_maker()() as db_session:
            return await process_ops.create_process(
                db_session, user, self.authorizer, to_create
            )

    async def update_process(
        self,
        process: process_schemas.Process,
        to_update: process_schemas.ProcessUpdate,
        user: Principal,
    ) -> process_schemas.Process:
        """Update an existing process."""
        async with self.config.get_db_session_maker()() as db_session:
            return await process_ops.update_process(
                db_session, user, self.authorizer, process, to_update
            )

    async def set_process_deployment_status(
        self,
        process: process_schemas.Process,
        value: process_schemas.ProcessDeploymentStatusValue,
        user: Principal,
        detail: str | None = None,
        *,
        deployed_reference: str | None = None,
        from_values: Collection[process_schemas.ProcessDeploymentStatusValue]
        | None = None,
        expected_definition_hash: str | None = None,
    ) -> process_schemas.Process:
        """update a process' deployment status."""
        async with self.config.get_db_session_maker()() as db_session:
            return await process_ops.set_process_deployment_status(
                db_session,
                user,
                self.authorizer,
                process,
                value=value,
                detail=detail,
                deployed_reference=deployed_reference,
                from_values=from_values,
                expected_definition_hash=expected_definition_hash,
            )

    async def delete_process(
        self,
        identifier: str,
        user: Principal,
    ) -> None:
        """Delete a process."""
        async with self.config.get_db_session_maker()() as db_session:
            return await process_ops.delete_process(
                db_session, user, self.authorizer, identifier
            )

    async def grant_process_access(
        self,
        *,
        granting_user: Principal,
        target_user_id: str,
        process: process_schemas.Process,
        role: str,
    ) -> None:
        """Grant a role on the input process to the target user."""
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.grant_process_access(
                db_session,
                granting_user,
                self.authorizer,
                target_user_id,
                process,
                role,
            )

    async def revoke_process_access(
        self,
        *,
        revoking_user: Principal,
        target_user_id: str,
        process: process_schemas.Process,
    ) -> None:
        """Revoke a user's access to a process."""
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.revoke_process_access(
                db_session,
                revoking_user,
                self.authorizer,
                target_user_id,
                process,
            )

    async def get_job_admin_view(self) -> BaseModelView | None:
        """Return a starlette_admin view suitable for use in potto's admin ui."""
        return None

    async def get_job_capabilities(self) -> job_schemas.JobManagerCapabilities:
        """Return the manager's capabilities."""
        return job_schemas.JobManagerCapabilities(
            supports_deletion=True, supports_deployment=True, supports_undeployment=True
        )

    @property
    def supported_deployment_types(self) -> tuple[Literal["cwl", "oci"] | str, ...]:
        """Report which deployment types are supported by the manager."""
        return "cwl", "oci"

    async def deploy_process(
        self, process: process_schemas.Process
    ) -> process_schemas.ProcessDeploymentStatus:
        """Deploy a process.

        This is a potential long-running task and should thus be called from a background worker.

        Raise DeploymentFailedException when the deployment cannot be done or fails.
        """
        match process.execution_unit:
            case process_schemas.ProcessExecutionUnitOci():
                return await self._deploy_oci_process(process)
            case process_schemas.ProcessExecutionUnitCwl():
                return await self._deploy_cwl_process(process)
            case _ as unsupported_type:
                raise exceptions.ProcessExecutionUnitNotSupportedError(
                    f"process execution unit "
                    f"{unsupported_type.type_ if unsupported_type else unsupported_type!r} "
                    f"is not supported "
                )

    async def _deploy_oci_process(
        self, process: process_schemas.Process
    ) -> process_schemas.ProcessDeploymentStatus:
        execution_unit = cast(
            process_schemas.ProcessExecutionUnitOci, process.execution_unit
        )
        try:
            reference = oci.parse_image_reference(execution_unit.image)
            oci.ensure_registry_allowed(reference, self.config.oci)
        except oci.OciImageReferenceError as err:
            raise exceptions.DeploymentFailedException(str(err)) from err
        repository = oci.process_repository(process)
        deployed = await self._run_with_docker_client(
            oci.pull_and_tag,
            reference,
            oci.get_auth_config(reference, self.config.oci),
            repository,
            process.get_deployment_hash(),
        )
        # earlier deployments of the process are no longer needed
        released = await self._run_with_docker_client(
            oci.release_tags, repository, deployed.local_reference
        )
        if released:
            logger.info(
                f"released earlier deployments of process {process.identifier!r}: "
                f"{released}"
            )
        return process_schemas.ProcessDeploymentStatus(
            value=process_schemas.ProcessDeploymentStatusValue.DEPLOYED,
            detail=(
                f"pulled {deployed.upstream_digest}"
                if deployed.upstream_digest
                else f"pulled {reference.repository}:{reference.tag_or_digest}"
            ),
            deployed_reference=deployed.local_reference,
        )

    async def _deploy_cwl_process(
        self, process: process_schemas.Process
    ) -> process_schemas.ProcessDeploymentStatus:
        raise NotImplementedError

    async def undeploy_process(self, process: process_schemas.Process) -> None:
        """Undeploy a process, releasing whatever its deployment produced."""
        match process.execution_unit:
            case process_schemas.ProcessExecutionUnitOci():
                released = await self._run_with_docker_client(
                    oci.release_tags, oci.process_repository(process)
                )
                logger.info(f"undeployed process {process.identifier!r}: {released}")
            case _:
                logger.debug(f"process {process.identifier!r} has nothing to undeploy")

    async def validate_execution_unit(
        self, execution_unit: process_schemas.ExecutionUnitInput
    ) -> None:
        """Check whether this manager would accept an execution unit for deployment."""
        match execution_unit:
            case process_schemas.ExecutionUnitOciCreate(image=image) | (
                process_schemas.ExecutionUnitOciUpdate(image=str() as image)
            ):
                try:
                    oci.ensure_registry_allowed(
                        oci.parse_image_reference(image), self.config.oci
                    )
                except oci.OciImageReferenceError as err:
                    raise exceptions.ProcessExecutionUnitRejectedError(
                        str(err)
                    ) from err
            case _:
                return None

    async def _run_with_docker_client(
        self, function: Callable[..., T], *args: Any
    ) -> T:
        """Run a synchronous function that takes a docker client, in a thread."""

        def run() -> T:
            settings = self.config.oci
            try:
                client = (
                    docker.DockerClient(
                        base_url=settings.docker_base_url,
                        timeout=settings.docker_timeout_seconds,
                    )
                    if settings.docker_base_url
                    else docker.from_env(timeout=settings.docker_timeout_seconds)
                )
            except docker.errors.DockerException as err:
                raise exceptions.DeploymentFailedException(
                    f"could not connect to the container engine: {err}"
                ) from err
            try:
                return function(client, *args)
            finally:
                client.close()

        return await asyncio.to_thread(run)

    async def get_job(
        self,
        identifier: str,
        user: Principal | None,
    ) -> job_schemas.Job | None:
        """Retrieve a job."""
        async with self.config.get_db_session_maker()() as db_session:
            return await job_ops.get_job(db_session, user, self.authorizer, identifier)

    async def paginated_list_jobs(
        self,
        user: Principal | None,
        *,
        page: int = 1,
        page_size: int = 20,
        include_total: bool = False,
        filter_: job_schemas.JobFilter | None = None,
    ) -> tuple[list[job_schemas.Job], int | None]:
        """Retrieve a list of jobs"""
        async with self.config.get_db_session_maker()() as db_session:
            return await job_ops.paginated_list_jobs(
                db_session,
                user,
                self.authorizer,
                page=page,
                page_size=page_size,
                include_total=include_total,
                identifiers_filter=filter_.identifiers if filter_ else None,
            )

    async def create_job(
        self,
        process_identifier: str,
        to_create: job_schemas.JobCreate,
        user: Principal | None,
    ) -> job_schemas.Job:
        """Create a new job for the process.

        The job is only recorded here - it gets executed later, when potto's
        background worker calls ``execute_job()``.
        """
        async with self.config.get_db_session_maker()() as db_session:
            return await job_ops.create_job(
                db_session, user, self.authorizer, process_identifier, to_create
            )

    async def execute_job(
        self,
        identifier: str,
        user: Principal,
    ) -> job_schemas.Job:
        """Execute a job, running it to completion."""
        async with self.config.get_db_session_maker()() as db_session:
            job, claimed = await job_ops.set_job_status(
                db_session,
                user,
                self.authorizer,
                identifier,
                job_schemas.JobStatus.RUNNING,
                from_statuses={job_schemas.JobStatus.ACCEPTED},
            )
        if not claimed:
            logger.debug(
                f"job {identifier!r} has status {job.status!r}, not executing it"
            )
            return job
        message: str | None = None
        progress: int | None = None
        exception: OgcApiException | None = None
        try:
            await self._run_job(job)
        except Exception as err:
            logger.exception(f"job {identifier!r} failed")
            outcome = job_schemas.JobStatus.FAILED
            message = str(err) or err.__class__.__name__
            exception = OgcApiException(
                type_=err.__class__.__name__,
                title="Job execution failed",
                detail=str(err) or None,
            )
        else:
            outcome = job_schemas.JobStatus.SUCCESSFUL
            progress = 100
        async with self.config.get_db_session_maker()() as db_session:
            # only a job that is still running gets its outcome recorded - it
            # may have been dismissed in the meantime
            job, finished = await job_ops.set_job_status(
                db_session,
                user,
                self.authorizer,
                identifier,
                outcome,
                from_statuses={job_schemas.JobStatus.RUNNING},
                message=message,
                progress=progress,
                exception=exception,
            )
        if not finished:
            logger.info(
                f"job {identifier!r} changed to status {job.status!r} while "
                f"running, not recording the outcome of its execution"
            )
        return job

    async def _run_job(self, job: job_schemas.Job) -> None:
        match job.process.execution_unit:
            case process_schemas.ProcessExecutionUnitOci():
                raise NotImplementedError(
                    "Execution of OCI processes is not implemented yet"
                )
            case process_schemas.ProcessExecutionUnitCwl():
                raise NotImplementedError(
                    "Execution of CWL processes is not implemented yet"
                )
            case _ as unsupported_type:
                raise exceptions.ProcessExecutionUnitNotSupportedError(
                    f"process execution unit "
                    f"{unsupported_type.type_ if unsupported_type else unsupported_type!r} "
                    f"is not supported "
                )

    async def set_job_status(
        self,
        identifier: str,
        status: job_schemas.JobStatus,
        user: Principal,
        *,
        message: str | None = None,
        progress: int | None = None,
        exception: OgcApiException | None = None,
    ) -> job_schemas.Job:
        """Update a job's status."""
        async with self.config.get_db_session_maker()() as db_session:
            job, _ = await job_ops.set_job_status(
                db_session,
                user,
                self.authorizer,
                identifier,
                status,
                message=message,
                progress=progress,
                exception=exception,
            )
        return job

    async def delete_job(
        self,
        identifier: str,
        user: Principal,
    ) -> None:
        """Delete a job."""
        async with self.config.get_db_session_maker()() as db_session:
            return await job_ops.delete_job(
                db_session, user, self.authorizer, identifier
            )


_manager_cache: dict[str, PostgisManager] = {}


def get_postgis_manager(
    raw_config: dict[str, Any],
    settings: "PottoSettings",
) -> PostgisManager:
    # PostgisManager implements several ...Protocol types, so this one factory
    # satisfies CollectionManagerFactoryProtocol/JobManagerFactoryProtocol/
    # ProcessManagerFactoryProtocol/ServerMetadataManagerFactoryProtocol/
    # UserAccountManagerFactoryProtocol at once - no separate wrapper per protocol needed.
    config = PostgisManagerConfiguration.model_validate(raw_config)
    # keyed on the whole configuration, rather than just the DSN, so that e.g. a
    # job manager configured with OCI settings does not end up sharing an instance
    # that was created from some other manager's configuration
    key = json.dumps(raw_config, sort_keys=True, default=str)
    if key not in _manager_cache:
        _manager_cache[key] = PostgisManager(config, settings)
    return _manager_cache[key]


def _get_current_and_head_revisions(
    alembic_config: alembic.config.Config,
) -> tuple[set[str], set[str]]:
    script = ScriptDirectory.from_config(alembic_config)
    head_revisions = set(script.get_heads())
    # always set by build_alembic_config(), the only place that constructs
    # an alembic_config for this function
    db_url = cast(str, alembic_config.get_main_option("sqlalchemy.url"))
    engine = create_engine(db_url)
    try:
        with engine.connect() as connection:
            current_revisions = set(
                MigrationContext.configure(connection).get_current_heads()
            )
    finally:
        engine.dispose()
    return current_revisions, head_revisions


async def _check_health(
    alembic_config: alembic.config.Config,
) -> Literal["ok", "not-ready", "error"]:
    """Check DB connectivity and whether it's stamped at the migrations head.

    Connects to the DB and compares its current alembic revision(s) against
    the migration scripts' head - this catches both an unreachable DB and one
    that's behind on migrations, without a separate connectivity check.

    Deliberately avoids alembic's autogenerate (e.g. ``alembic.command.check``,
    used by the CLI's ``check_for_changes``): autogenerate's diffing mutates
    shared SQLAlchemy metadata for enum-typed columns as a side effect (a bug
    in ``alembic_postgresql_enum``'s autogenerate hook, which reassigns
    ``column.type`` in place on the actual mapped ``Table`` objects rather
    than a copy, whenever it has to render a ``CreateTableOp``/``AddColumnOp``
    for one). That's tolerable for a one-off CLI command, but this check runs
    against a live, long-running server process - the first time it observes
    a missing/outdated table it would permanently corrupt that column's
    ``enum_class`` for the rest of the process's life (breaking, e.g., the
    admin UI's ``CollectionView``). A plain revision-vs-head comparison never
    touches autogenerate at all, so it can't trigger that bug - the trade-off
    is that it won't catch a DB that's stamped at head but whose live schema
    was hand-edited to no longer match the models.
    """
    try:
        current_revisions, head_revisions = await asyncio.to_thread(
            _get_current_and_head_revisions, alembic_config
        )
    except Exception:
        return "error"

    if current_revisions == head_revisions:
        return "ok"
    return "not-ready"
