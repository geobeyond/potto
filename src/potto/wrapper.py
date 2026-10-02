import dataclasses
import datetime as dt
import logging
from typing import (
    cast,
    Literal,
    Sequence,
    TypeAlias,
)

from faststream.mqtt import QoS

from . import exceptions as potto_exceptions
from .authz.authorizer import (
    Principal,
)
from .schemas.auth import SystemPrincipal
from .constants import (
    ConformanceClass,
    CRS_84,
    JOB_INTERNAL_TOPIC_PREFIX,
    PROCESS_INTERNAL_TOPIC_PREFIX,
)
from .config import PottoSettings
from .providers.features import get_feature_provider
from .pubsub.audience import (
    resolve_job_audience,
    resolve_process_audience,
)
from .schemas import (
    collections as collection_schemas,
    jobs as job_schemas,
    pagination as pagination_schemas,
    processes as process_schemas,
    features as feature_schemas,
    events,
    system as system_schemas,
)
from .util import (
    create_correlation_id,
    get_collection_pagination_limit,
)

logger = logging.getLogger(__name__)

ResourceTypes: TypeAlias = Sequence[Literal["collection", "stac-collection", "process"]]


class Potto:
    _settings: PottoSettings

    def __init__(
        self,
        settings: PottoSettings,
    ) -> None:
        self._settings = settings

    async def get_overview(
        self,
        *,
        user: Principal | None,
    ) -> system_schemas.SystemOverview:
        """Return overview information.

        The response contains useful info for generating a landing page for the API.
        """

        page = 1
        collection_manager = self._settings.get_collection_manager()
        collections, total = await collection_manager.paginated_list_collections(
            user, page=page, include_total=True
        )
        server_metadata = (
            await self._settings.get_server_metadata_manager().get_server_metadata()
        )
        return system_schemas.SystemOverview(
            metadata=server_metadata,
            collections=collection_schemas.CollectionList(
                collections=collections,
                pagination=pagination_schemas.Pagination(
                    page=page,
                    page_size=len(collections),
                    total=total or 0,
                ),
            ),
        )

    async def get_health_status(self) -> system_schemas.HealthCheck:
        """Check DB connectivity, schema freshness, and internal broker reachability.

        Broker reachability is informational only and does not affect the aggregate
        `status` - the internal broker being briefly unreachable shouldn't fail
        readiness/liveness probes when every DB-backed request still works fine.
        """
        collection_manager = self._settings.get_collection_manager()
        collection_manager_health = await collection_manager.check_health()
        broker_reachable = await self._settings.get_internal_broker(role="api").ping(
            timeout=3.0
        )
        return system_schemas.HealthCheck(
            status="ok" if collection_manager_health == "ok" else "error",
            collection_manager=collection_manager_health,
            internal_broker="ok" if broker_reachable else "error",
        )

    async def get_conformance_details(self) -> system_schemas.ConformanceDetail:
        return system_schemas.ConformanceDetail(
            conforms_to=[
                ConformanceClass.OGCAPI_FEATURES_CORE,
                ConformanceClass.OGCAPI_FEATURES_GEOJSON,
                ConformanceClass.OGCAPI_FEATURES_OPENAPI3,
                ConformanceClass.OGCAPI_FEATURES_PART2_CRS,
            ]
        )

    async def list_collections(
        self,
        *,
        user: Principal | None,
        page: int = 1,
        page_size: int = 20,
    ) -> collection_schemas.CollectionList:
        collection_manager = self._settings.get_collection_manager()
        collections, total = await collection_manager.paginated_list_collections(
            user,
            page=page,
            page_size=page_size,
            include_total=True,
        )
        return collection_schemas.CollectionList(
            collections=collections,
            pagination=pagination_schemas.Pagination(
                page=page,
                page_size=len(collections),
                total=cast(int, total),
            ),
        )

    async def get_collection(
        self,
        collection_id: str,
        *,
        user: Principal | None,
        include_queryables: bool = False,
        include_schema: bool = False,
    ) -> collection_schemas.Collection | None:
        collection_manager = self._settings.get_collection_manager()
        if (
            collection := await collection_manager.get_collection(collection_id, user)
        ) is None:
            return None
        if not any((include_queryables, include_schema)):
            return collection

        if (
            feature_provider := await get_feature_provider(collection, self._settings)
        ) is None:
            raise potto_exceptions.PottoException(
                "Cannot return schema nor queryables - unable to get feature provider"
            )

        if include_queryables:
            collection = dataclasses.replace(
                collection, queryables=await feature_provider.get_queryables()
            )
        if include_schema:
            collection = dataclasses.replace(
                collection, schema=await feature_provider.get_schema()
            )
        return collection

    async def list_collection_items(
        self,
        collection_id: str,
        *,
        user: Principal | None = None,
        filter_: feature_schemas.PottoFeatureFilter | None = None,
    ) -> feature_schemas.FeatureList:
        feature_filter = filter_ or feature_schemas.PottoFeatureFilter()
        collection_manager = self._settings.get_collection_manager()
        if (
            collection := await collection_manager.get_collection(collection_id, user)
        ) is None:
            raise potto_exceptions.PottoCollectionNotFoundException(collection_id)
        effective_pagination_limit = get_collection_pagination_limit(
            feature_filter.limit if feature_filter else None, collection, self._settings
        )

        if (
            feature_provider := await get_feature_provider(collection, self._settings)
        ) is None:
            return feature_schemas.FeatureList(
                collection=collection,
                features=[],
                pagination=pagination_schemas.PaginationContext(
                    limit=effective_pagination_limit,
                    offset=feature_filter.offset,
                    number_returned=0,
                    number_matched=0,
                ),
                filter_=feature_filter,
                metadata={},
            )
        features = await feature_provider.list_features(feature_filter)
        feature_count = await feature_provider.count_items(feature_filter)
        return feature_schemas.FeatureList(
            collection=collection,
            features=features,
            pagination=pagination_schemas.PaginationContext(
                limit=effective_pagination_limit,
                offset=feature_filter.offset,
                number_returned=len(features),
                number_matched=feature_count.matched,
            ),
            filter_=feature_filter,
            metadata={},
        )

    async def get_collection_item(
        self,
        user: Principal | None,
        *,
        item_id: str,
        collection_id: str,
        crs: str | None = None,
    ) -> feature_schemas.AugmentedFeature:

        collection_manager = self._settings.get_collection_manager()
        if (
            collection := await collection_manager.get_collection(collection_id, user)
        ) is None:
            raise potto_exceptions.PottoCollectionNotFoundException(collection_id)
        if (
            feature_provider := await get_feature_provider(collection, self._settings)
        ) is None:
            raise potto_exceptions.PottoException(
                f"Collection {collection_id!r} does not have a feature provider"
            )
        if (feat := await feature_provider.get_feature(item_id, crs or CRS_84)) is None:
            raise potto_exceptions.PottoCollectionItemNotFoundException(
                f"Item {item_id} not found"
            )
        return feature_schemas.AugmentedFeature(
            collection=collection,
            feature=feat,
            metadata={},
        )

    async def list_processes(
        self,
        *,
        user: Principal | None,
        page: int = 1,
        page_size: int = 20,
    ) -> process_schemas.ProcessList:
        process_manager = self._settings.get_process_manager()
        processes, total = await process_manager.paginated_list_processes(
            user,
            page=page,
            page_size=page_size,
            include_total=True,
        )
        return process_schemas.ProcessList(
            processes=processes,
            pagination=pagination_schemas.Pagination(
                page=page,
                page_size=len(processes),
                total=cast(int, total),
            ),
        )

    async def get_process(
        self,
        process_id: str,
        *,
        user: Principal | None,
    ) -> process_schemas.Process | None:
        process_manager = self._settings.get_process_manager()
        return await process_manager.get_process(process_id, user)

    async def create_process(
        self,
        to_create: process_schemas.ProcessCreate,
        *,
        user: Principal,
        correlation_id: str | None = None,
    ) -> process_schemas.Process:
        """Create a new process.

        Upon successful process creation, this also publishes a ``ProcessEvent``
        to the ``processes/{identifier}/created`` topic.
        """
        await self._settings.get_job_manager().validate_execution_unit(
            to_create.execution_unit
        )
        process_manager = self._settings.get_process_manager()
        created = await process_manager.create_process(to_create, user)
        await self.publish_internal_process_event(
            events.InternalProcessEvent(
                event_type=events.InternalProcessEventType.CREATED,
                process_identifier=created.identifier,
                initiated_by=user,
                timestamp=dt.datetime.now(dt.timezone.utc),
                correlation_id=correlation_id or create_correlation_id(),
            )
        )
        return created

    async def update_process(
        self,
        process_id: str,
        to_update: process_schemas.ProcessUpdate,
        *,
        user: Principal,
        correlation_id: str | None = None,
    ) -> process_schemas.Process:
        """Update an existing process.

        Upon successful process modification, this also publishes a ``ProcessEvent``
        to the ``processes/{identifier}/updated`` topic.
        """
        process_manager = self._settings.get_process_manager()
        if (process := await process_manager.get_process(process_id, user)) is None:
            raise potto_exceptions.CannotUpdateResourceError(
                f"process {process_id} not found"
            )
        await self._settings.get_job_manager().validate_execution_unit(
            to_update.execution_unit
        )
        updated = await process_manager.update_process(process, to_update, user)
        await self.publish_internal_process_event(
            events.InternalProcessEvent(
                event_type=events.InternalProcessEventType.UPDATED,
                process_identifier=updated.identifier,
                initiated_by=user,
                timestamp=dt.datetime.now(dt.timezone.utc),
                correlation_id=correlation_id or create_correlation_id(),
            )
        )
        return updated

    async def delete_process(
        self,
        process_id: str,
        *,
        user: Principal,
        correlation_id: str | None = None,
    ) -> None:
        """Delete a process.

        Upon successful process modification, this also publishes a ``ProcessEvent``
        to the ``processes/{identifier}/deleted`` topic.
        """
        process_manager = self._settings.get_process_manager()
        if (
            process := await process_manager.get_process(
                process_id, SystemPrincipal("process-deleter")
            )
        ) is None:
            raise potto_exceptions.CannotDeleteResourceError(
                f"process {process_id} not found"
            )
        # the audience must be resolved before deleting, as it can no longer be
        # resolved by looking up the process afterwards
        audience = await resolve_process_audience(process, self._settings)
        await process_manager.delete_process(process_id, user)
        await self.publish_internal_process_event(
            events.InternalProcessDeletionEvent(
                process_identifier=process_id,
                initiated_by=user,
                timestamp=dt.datetime.now(dt.timezone.utc),
                correlation_id=correlation_id or create_correlation_id(),
                audience=audience,
                process=process,
            )
        )

    async def deploy_process(
        self,
        process_id: str,
        *,
        user: Principal,
        correlation_id: str | None = None,
    ) -> process_schemas.Process:
        """Deploy a process.

        Deploying a process requires coordination between the process manager
        (which knows details about processes and is allowed to modify them) and
        the job manager (which knows how to deploy processes and how to run them).

        Upon successful deployment, this also publishes a ``ProcessEvent`` to
        the ``processes/{identifier}/deployed`` topic.
        """
        correlation_id = correlation_id or create_correlation_id()
        if (process := await self.get_process(process_id, user=user)) is None:
            raise potto_exceptions.DeploymentFailedException(
                f"process {process_id} not found"
            )
        status_value = process_schemas.ProcessDeploymentStatusValue
        process_manager = self._settings.get_process_manager()
        try:
            # claiming the deployment is atomic, so that concurrent workers do not
            # deploy the same process at the same time
            claimed = await process_manager.set_process_deployment_status(
                process,
                value=status_value.IN_PROGRESS,
                user=user,
                from_values={
                    status_value.QUEUED,
                    status_value.DEPLOYED,
                    status_value.FAILED,
                },
            )
        except potto_exceptions.ProcessDeploymentStatusConflictError as err:
            raise potto_exceptions.DeploymentAlreadyInProgressError(
                f"process {process_id} is already being deployed"
            ) from err

        job_manager = self._settings.get_job_manager()
        deployed_reference: str | None = None
        try:
            deployment_status = await job_manager.deploy_process(claimed)
            outcome, detail = deployment_status.value, deployment_status.detail
            deployed_reference = deployment_status.deployed_reference
        except Exception as err:
            # the deployment must not be left in progress forever
            logger.exception(f"failed to deploy process {process_id}")
            outcome, detail = status_value.FAILED, str(err) or err.__class__.__name__

        try:
            # only the deployment that claimed the process gets to record its
            # outcome - this guards against the outcome of a deployment that was
            # started for an older definition overwriting that of a newer one
            deployed = await process_manager.set_process_deployment_status(
                claimed,
                value=outcome,
                user=user,
                detail=detail,
                deployed_reference=deployed_reference,
                from_values={status_value.IN_PROGRESS},
                expected_definition_hash=claimed.deployment_status.definition_hash,
            )
        except potto_exceptions.ProcessDeploymentStatusConflictError:
            logger.info(
                f"deployment status of process {process_id} changed while it was "
                f"being deployed, not recording the outcome of its deployment"
            )
            return claimed
        except potto_exceptions.ResourceNotFoundError:
            # the process was deleted while it was being deployed. Its deletion
            # event may well have been handled already, so this deployment needs
            # to be released here, as nothing else would
            logger.info(
                f"process {process_id} was deleted while it was being deployed, "
                f"undeploying it"
            )
            await self.undeploy_process(
                claimed, user=user, correlation_id=correlation_id
            )
            return claimed

        # the event also triggers the process reconciler, which redeploys the
        # process if its definition changed while it was being deployed
        await self.publish_internal_process_event(
            events.InternalProcessEvent(
                event_type=(
                    events.InternalProcessEventType.DEPLOYED
                    if outcome == status_value.DEPLOYED
                    else events.InternalProcessEventType.DEPLOYMENT_FAILED
                ),
                process_identifier=process_id,
                initiated_by=user,
                timestamp=dt.datetime.now(dt.timezone.utc),
                correlation_id=correlation_id,
            )
        )
        return deployed

    async def undeploy_process(
        self,
        process: process_schemas.Process,
        *,
        user: Principal,
        correlation_id: str | None = None,
    ) -> None:
        """Undeploy a process that has been deleted.

        ``process`` is a snapshot of the process as it was just before its
        deletion. This is a potentially long-running task and should thus be
        called from a background worker.

        Unlike other process operations, this publishes no event - the process no
        longer exists, and any process event would trigger reconciling it again.
        """
        try:
            await self._settings.get_job_manager().undeploy_process(process)
        except Exception:
            logger.exception(
                f"failed to undeploy process {process.identifier} "
                f"(correlation id {correlation_id})"
            )

    async def publish_internal_process_event(
        self,
        event: events.InternalProcessEvent | events.InternalProcessDeletionEvent,
    ) -> None:
        broker = self._settings.get_internal_broker(role="api")
        try:
            await broker.publish(
                message=event,
                topic="/".join(
                    (
                        PROCESS_INTERNAL_TOPIC_PREFIX,
                        event.process_identifier,
                        event.event_type.value,
                    )
                ),
                qos=QoS.AT_LEAST_ONCE,
            )
        except Exception:
            logger.exception(
                f"failed to publish {event.event_type.value} for process "
                f"{event.process_identifier}"
            )

    async def list_jobs(
        self,
        *,
        user: Principal | None,
        page: int = 1,
        page_size: int = 20,
    ) -> job_schemas.JobList:
        job_manager = self._settings.get_job_manager()
        jobs, total = await job_manager.paginated_list_jobs(
            user,
            page=page,
            page_size=page_size,
            include_total=True,
        )
        return job_schemas.JobList(
            jobs=jobs,
            pagination=pagination_schemas.Pagination(
                page=page,
                page_size=len(jobs),
                total=cast(int, total),
            ),
        )

    async def get_job(
        self,
        job_id: str,
        *,
        user: Principal | None,
    ) -> job_schemas.Job | None:
        job_manager = self._settings.get_job_manager()
        return await job_manager.get_job(job_id, user)

    async def create_job(
        self,
        process_id: str,
        to_create: job_schemas.JobCreate,
        *,
        user: Principal | None,
        correlation_id: str | None = None,
    ) -> job_schemas.Job:
        """Create a new job, which is meant to eventually execute a process.

        Upon successful job creation, this also publishes an ``InternalJobEvent``
        to the ``jobs/{identifier}/created`` topic. The job is then executed by
        potto's background worker, as a reaction to this event.
        """
        job_manager = self._settings.get_job_manager()
        created = await job_manager.create_job(process_id, to_create, user)
        await self.publish_internal_job_event(
            events.InternalJobEvent(
                event_type=events.InternalJobEventType.CREATED,
                job_identifier=created.identifier,
                initiated_by=user,
                timestamp=dt.datetime.now(dt.timezone.utc),
                correlation_id=correlation_id or create_correlation_id(),
            )
        )
        return created

    async def execute_job(
        self,
        job_id: str,
        *,
        user: Principal,
        correlation_id: str | None = None,
    ) -> job_schemas.Job:
        """Execute a job.

        This is a potentially long-running task and should thus be called from a
        background worker.

        If the job's status changes, this also publishes an ``InternalJobEvent``
        to the ``jobs/{identifier}/status_changed`` topic.
        """
        job_manager = self._settings.get_job_manager()
        if (job := await job_manager.get_job(job_id, user)) is None:
            raise potto_exceptions.ResourceNotFoundError(f"job {job_id} not found")
        executed = await job_manager.execute_job(job_id, user)
        if executed.status != job.status:
            await self.publish_internal_job_event(
                events.InternalJobEvent(
                    event_type=events.InternalJobEventType.STATUS_CHANGED,
                    job_identifier=executed.identifier,
                    initiated_by=user,
                    timestamp=dt.datetime.now(dt.timezone.utc),
                    correlation_id=correlation_id or create_correlation_id(),
                )
            )
        return executed

    async def delete_job(
        self,
        job_id: str,
        *,
        user: Principal,
        correlation_id: str | None = None,
    ) -> None:
        """Delete a job.

        Upon successful job deletion, this also publishes an
        ``InternalJobDeletionEvent`` to the ``jobs/{identifier}/deleted`` topic.
        """
        job_manager = self._settings.get_job_manager()
        if (
            job := await job_manager.get_job(job_id, SystemPrincipal("job-deleter"))
        ) is None:
            raise potto_exceptions.CannotDeleteResourceError(f"job {job_id} not found")
        # the audience must be resolved before deleting, as it can no longer be
        # resolved by looking up the job afterwards
        audience = await resolve_job_audience(job, self._settings)
        await job_manager.delete_job(job_id, user)
        await self.publish_internal_job_event(
            events.InternalJobDeletionEvent(
                job_identifier=job_id,
                initiated_by=user,
                timestamp=dt.datetime.now(dt.timezone.utc),
                correlation_id=correlation_id or create_correlation_id(),
                audience=audience,
            )
        )

    async def publish_internal_job_event(
        self,
        event: events.InternalJobEvent | events.InternalJobDeletionEvent,
    ) -> None:
        broker = self._settings.get_internal_broker(role="api")
        try:
            await broker.publish(
                message=event,
                topic="/".join(
                    (
                        JOB_INTERNAL_TOPIC_PREFIX,
                        event.job_identifier,
                        event.event_type.value,
                    )
                ),
                qos=QoS.AT_LEAST_ONCE,
            )
        except Exception:
            logger.exception(
                f"failed to publish {event.event_type.value} for job "
                f"{event.job_identifier}"
            )
