"""Potto feature provider that uses the collection config as its store.

This is a simple provider that is intended mainly for using in tests.
"""

import logging
from typing import (
    Any,
    Literal,
    TYPE_CHECKING,
)

import pydantic
from pydantic.json_schema import JsonSchemaValue

from ... import constants
from ...schemas.base import (
    AdditionalExtent,
    CountedItems,
    StorageCrs,
    TemporalExtent,
    ThreeDimensionSpatialExtent,
    TwoDimensionalSpatialExtent,
)

if TYPE_CHECKING:
    from ...config import PottoSettings
    from ...schemas.base import PottoFeatureFilter
    from ...schemas.potto import (
        Collection,
        Feature,
    )

logger = logging.getLogger(__name__)


class WktFeatureItem(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid", populate_by_name=True)
    id_: str = pydantic.Field(alias="id")
    properties: dict[str, Any] = pydantic.Field(default_factory=dict)
    geometry: str


class CollectionConfigFeatureProviderConfiguration(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")
    provider_name: Literal["collection-config"] = "collection-config"
    raw_features: list[WktFeatureItem]
    storage_crs: str = constants.CRS_84


class CollectionConfigFeatureProvider:
    """Read-only feature provider that stores features in the collection configuration."""

    def __init__(
        self,
        config: CollectionConfigFeatureProviderConfiguration,
    ) -> None:
        self.config = config

    async def list_features(
        self,
        feature_filter: "PottoFeatureFilter | None" = None,
    ) -> list["Feature"]:
        return []

    async def count_items(
        self, feature_filter: "PottoFeatureFilter | None" = None
    ) -> CountedItems:
        return CountedItems(total=0, matched=0)

    async def get_feature(
        self,
        feature_id: str,
        crs: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
    ) -> "Feature | None":
        return None

    async def get_schema(self) -> JsonSchemaValue:
        return JsonSchemaValue({})

    async def get_queryables(self) -> JsonSchemaValue:
        return JsonSchemaValue({})

    async def get_storage_crs(self) -> StorageCrs | None:
        return None

    async def get_spatial_extent(
        self,
    ) -> TwoDimensionalSpatialExtent | ThreeDimensionSpatialExtent | None:
        return None

    async def get_temporal_extent(self) -> TemporalExtent | None:
        return None

    async def get_additional_extents(self) -> list[AdditionalExtent] | None:
        return None


async def collection_config_provider_factory(
    collection: "Collection",
    raw_config: dict[str, Any],
    potto_config: "PottoSettings",
) -> CollectionConfigFeatureProvider:
    config = CollectionConfigFeatureProviderConfiguration.model_validate(raw_config)
    return CollectionConfigFeatureProvider(config)
