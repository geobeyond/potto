import dataclasses
import logging
from typing import (
    cast,
    Literal,
    Sequence,
    TypeAlias,
)

from . import exceptions as potto_exceptions
from .constants import (
    ConformanceClass,
    CRS_84,
)
from .config import PottoSettings
from .db.alembic_utils import build_alembic_config
from .operations import (
    health as health_ops,
    metadata as metadata_ops,
)
from .providers.features import get_feature_provider
from .schemas.auth import PottoUser
from .schemas.collections import (
    Collection,
    CollectionList,
)
from .schemas.features import (
    AugmentedFeature,
    FeatureList,
    PottoFeatureFilter,
)
from .schemas.pagination import (
    Pagination,
    PaginationContext,
)
from .schemas.system import (
    ConformanceDetail,
    HealthCheck,
    SystemOverview,
)
from .util import get_collection_pagination_limit

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
        user: PottoUser | None,
    ) -> SystemOverview:
        """Return overview information.

        The response contains useful info for generating a landing page for the API.
        """

        page = 1
        collection_manager = self._settings.get_collection_manager()
        collections, total = await collection_manager.paginated_list_collections(
            user, page=page, include_total=True)
        async with self._settings.get_db_session_maker()() as session:
            server_metadata = await metadata_ops.get_server_metadata(session)
        return SystemOverview(
            metadata=server_metadata.to_potto(),
            collections=CollectionList(
                collections=collections,
                pagination=Pagination(
                    page=page,
                    page_size=len(collections),
                    total=total or 0,
                ),
            ),
        )

    async def get_health_status(self) -> HealthCheck:
        """Check DB connectivity and whether its schema is up to date."""
        collection_manager = self._settings.get_collection_manager()
        collection_manager_health = await collection_manager.check_health()
        return HealthCheck(
            status="ok" if collection_manager_health == "ok" else "error",
            collection_manager=collection_manager_health,
        )

    async def get_conformance_details(self) -> ConformanceDetail:
        return ConformanceDetail(
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
        user: PottoUser | None,
        page: int = 1,
        page_size: int = 20,
    ) -> CollectionList:
        collection_manager = self._settings.get_collection_manager()
        collections, total = await collection_manager.paginated_list_collections(
            user, page=page, page_size=page_size, include_total=True,
        )
        return CollectionList(
            collections=collections,
            pagination=Pagination(
                page=page,
                page_size=len(collections),
                total=cast(int, total),
            ),
        )

    async def get_collection(
        self,
        collection_id: str,
        *,
        user: PottoUser | None,
        include_queryables: bool = False,
        include_schema: bool = False,
    ) -> Collection | None:
        collection_manager = self._settings.get_collection_manager()
        if (collection := await collection_manager.get_collection(collection_id, user)) is None:
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
        user: PottoUser | None = None,
        filter_: PottoFeatureFilter | None = None,
    ) -> FeatureList:
        feature_filter = filter_ or PottoFeatureFilter()
        collection_manager = self._settings.get_collection_manager()
        if (collection := await collection_manager.get_collection(collection_id, user)) is None:
            raise potto_exceptions.PottoCollectionNotFoundException(collection_id)
        effective_pagination_limit = get_collection_pagination_limit(
            feature_filter.limit if feature_filter else None, collection, self._settings
        )

        if (
            feature_provider := await get_feature_provider(collection, self._settings)
        ) is None:
            return FeatureList(
                collection=collection,
                features=[],
                pagination=PaginationContext(
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
        return FeatureList(
            collection=collection,
            features=features,
            pagination=PaginationContext(
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
        user: PottoUser | None,
        *,
        item_id: str,
        collection_id: str,
        crs: str | None = None,
    ) -> AugmentedFeature:

        collection_manager = self._settings.get_collection_manager()
        if (collection := await collection_manager.get_collection(collection_id, user)) is None:
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
        return AugmentedFeature(
            collection=collection,
            feature=feat,
            metadata={},
        )
