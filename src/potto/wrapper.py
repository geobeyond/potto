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
from .constants import (
    ConformanceClass,
    CRS_84,
    PROCESS_INTERNAL_TOPIC_PREFIX,
)
from .config import PottoSettings
from .providers.features import get_feature_provider
from .schemas import (
    collections as collection_schemas,
    pagination as pagination_schemas,
    processes as process_schemas,
    features as feature_schemas,
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
        process_manager = self._settings.get_process_manager()
        created = await process_manager.create_process(to_create, user)
        await self.publish_internal_process_event(
            created.identifier,
            process_schemas.ProcessEventType.CREATED,
            user,
            correlation_id=correlation_id or create_correlation_id(),
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
            raise potto_exceptions.CannotUpdateResourceException(
                f"process {process_id} not found"
            )
        updated = await process_manager.update_process(process, to_update, user)
        await self.publish_internal_process_event(
            updated.identifier,
            process_schemas.ProcessEventType.UPDATED,
            user,
            correlation_id=correlation_id or create_correlation_id(),
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
        await process_manager.delete_process(process_id, user)
        await self.publish_internal_process_event(
            process_id,
            process_schemas.ProcessEventType.DELETED,
            user,
            correlation_id=correlation_id or create_correlation_id(),
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

        if process.deployment_status.value in ("queued", "in-progress"):
            raise potto_exceptions.DeploymentAlreadyInProgressError

        # TODO: We may need to come up with some sort of ``process_manager.get_lock(process)``
        process_manager = self._settings.get_process_manager()
        await process_manager.set_process_deployment_status(
            process,
            value=process_schemas.ProcessDeploymentStatusValue.IN_PROGRESS,
            user=user,
        )

        # job_manager = self._settings.get_job_manager()
        # deployment_status_value, detail = await job_manager.deploy_process(process.execution_unit)
        # up_to_date_process = await process_manager.set_process_deployment_status(
        #     process,
        #     value=deployment_status_value,
        #     detail=detail,
        # )
        # await self.publish_internal_process_event(
        #     process_id,
        #     (
        #         process_schemas.ProcessEventType.DEPLOYED
        #         if deployment_status_value == process_schemas.ProcessDeploymentStatusValue.DEPLOYED
        #         else process_schemas.ProcessEventType.DEPLOYMENT_FAILED
        #     ),
        #     user,
        #     correlation_id=correlation_id,
        # )

        # should be ``return up_to_date_process`` instead
        return process

    async def undeploy_process(
        self,
        process_id: str,
        *,
        user: Principal,
        correlation_id: str | None = None,
    ) -> process_schemas.Process:
        """Undeploy a process.

        Upon successful undeployment, this also publishes a ``ProcessEvent`` to
        the ``processes/{identifier}/undeployed`` topic.
        """

        raise NotImplementedError

    async def publish_internal_process_event(
        self,
        process_id: str,
        event_type: process_schemas.ProcessEventType,
        initiated_by: Principal,
        correlation_id: str | None = None,
    ):
        event = process_schemas.ProcessEvent(
            event_type=event_type,
            process_identifier=process_id,
            timestamp=dt.datetime.now(dt.timezone.utc),
            correlation_id=correlation_id or create_correlation_id(),
            initiated_by=initiated_by,
        )
        broker = self._settings.get_internal_broker(role="api")
        try:
            await broker.publish(
                message=event,
                topic="/".join(
                    (
                        PROCESS_INTERNAL_TOPIC_PREFIX,
                        process_id,
                        event_type.value,
                    )
                ),
                qos=QoS.AT_LEAST_ONCE,
            )
        except Exception:
            logger.exception(
                f"failed to publish {event.event_type.value} for process {process_id}"
            )
