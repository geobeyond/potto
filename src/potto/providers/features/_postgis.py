from typing import (
    Any,
    Literal,
)

import pydantic
from pydantic.json_schema import JsonSchemaValue
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import PottoSettings
from ...schemas.potto import Feature
from ...schemas.base import (
    CountedItems,
    PottoFeatureFilter,
)


class PostgisFeatureProviderConfiguration(pydantic.BaseModel):
    provider_name: Literal["postgis"] = "postgis"


class PostgisFeatureProvider:
    config: PostgisFeatureProviderConfiguration
    db_session: AsyncSession
    potto_config: PottoSettings

    def __init__(
        self,
        config: PostgisFeatureProviderConfiguration,
        session: AsyncSession,
        potto_config: PottoSettings,
    ):
        """A feature provider that uses PostGIS to retrieve data."""
        self.config = config
        self.db_session = session
        self.potto_config = potto_config

    async def list_features(
        self, feature_filter: PottoFeatureFilter | None = None
    ) -> list[Feature]:
        raise NotImplementedError

    async def count_items(
        self, feature_filter: PottoFeatureFilter | None = None
    ) -> CountedItems:
        raise NotImplementedError

    async def get_feature(
        self,
        feature_id: str,
        crs: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
    ) -> Feature | None:
        raise NotImplementedError

    async def get_schema(self) -> JsonSchemaValue:
        raise NotImplementedError


def postgis_provider_factory(
    raw_config: dict[str, Any],
    session: AsyncSession,
    potto_config: PottoSettings,
) -> PostgisFeatureProvider:
    config = PostgisFeatureProviderConfiguration.model_validate(raw_config)
    return PostgisFeatureProvider(config, session, potto_config)
