import dataclasses
import logging
from typing import (
    cast,
    Literal,
    Sequence,
    TypeAlias,
)

from sqlmodel.ext.asyncio.session import AsyncSession

from . import exceptions as potto_exceptions
from .constants import (
    ConformanceClass,
    CRS_84,
)
from .config import PottoSettings
from .db.alembic_utils import build_alembic_config
from .operations import (
    collections as collection_ops,
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
        async with self._settings.get_db_session_maker()() as session:
            db_collections, total = await collection_ops.paginated_list_collections(
                session,
                user,
                self._settings.get_authorization_backend(),
                page=page,
                include_total=True,
            )
            server_metadata = await metadata_ops.get_server_metadata(session)
        assert total is not None
        return SystemOverview(
            metadata=server_metadata.to_potto(),
            collections=CollectionList(
                collections=[db_col.to_potto() for db_col in db_collections],
                pagination=Pagination(
                    page=page,
                    page_size=len(db_collections),
                    total=total,
                ),
            ),
        )

    async def get_health_status(self) -> HealthCheck:
        """Check DB connectivity and whether its schema is up to date."""
        return await health_ops.check_health(build_alembic_config(self._settings))

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
        session: AsyncSession,
        page: int = 1,
        page_size: int = 20,
    ) -> CollectionList:
        db_collections, total = await collection_ops.paginated_list_collections(
            session=session,
            authorization_backend=self._settings.get_authorization_backend(),
            user=user,
            page=page,
            page_size=page_size,
            include_total=True,
        )
        potto_collections = [db_col.to_potto() for db_col in db_collections]
        return CollectionList(
            collections=potto_collections,
            pagination=Pagination(
                page=page,
                page_size=len(potto_collections),
                total=cast(int, total),
            ),
        )

    async def get_collection(
        self,
        collection_id: str,
        *,
        user: PottoUser | None,
        session: AsyncSession,
        include_queryables: bool = False,
        include_schema: bool = False,
    ) -> Collection | None:
        if (
            db_collection := await collection_ops.get_collection_by_resource_identifier(
                session, user, self._settings.get_authorization_backend(), collection_id
            )
        ) is None:
            return None
        potto_collection = db_collection.to_potto()
        if not any((include_queryables, include_schema)):
            return potto_collection

        if (
            feature_provider := await get_feature_provider(
                potto_collection, self._settings
            )
        ) is None:
            raise potto_exceptions.PottoException(
                "Cannot return schema nor queryables - unable to get feature provider"
            )

        if include_queryables:
            potto_collection = dataclasses.replace(
                potto_collection, queryables=await feature_provider.get_queryables()
            )
        if include_schema:
            potto_collection = dataclasses.replace(
                potto_collection, schema=await feature_provider.get_schema()
            )
        return potto_collection

    async def list_collection_items(
        self,
        collection_id: str,
        *,
        user: PottoUser | None = None,
        filter_: PottoFeatureFilter | None = None,
        session: AsyncSession,
    ) -> FeatureList:
        feature_filter = filter_ or PottoFeatureFilter()
        if (
            collection := await self.get_collection(
                collection_id, user=user, session=session
            )
        ) is None:
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
        session: AsyncSession,
        item_id: str,
        collection_id: str,
        crs: str | None = None,
    ) -> AugmentedFeature:

        if (
            collection := await self.get_collection(
                collection_id, user=user, session=session
            )
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
        return AugmentedFeature(
            collection=collection,
            feature=feat,
            metadata={},
        )
