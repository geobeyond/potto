from typing import (
    Protocol,
    runtime_checkable,
    TYPE_CHECKING,
)

from pydantic.json_schema import JsonSchemaValue

if TYPE_CHECKING:
    from ...schemas.base import (
        AdditionalExtent,
        CountedItems,
        PottoFeatureFilter,
        StorageCrs,
        TemporalExtent,
        ThreeDimensionSpatialExtent,
        TwoDimensionalSpatialExtent,
    )
    from ...schemas.potto import Feature


@runtime_checkable
class FeatureProviderProtocol(Protocol):
    async def list_features(
        self,
        feature_filter: "PottoFeatureFilter | None" = None,
    ) -> list["Feature"]: ...

    async def count_items(
        self, feature_filter: "PottoFeatureFilter | None" = None
    ) -> "CountedItems": ...

    async def get_feature(
        self,
        feature_id: str,
        crs: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
    ) -> "Feature | None": ...

    async def get_schema(self) -> JsonSchemaValue: ...

    async def get_queryables(self) -> JsonSchemaValue: ...

    async def get_storage_crs(self) -> "StorageCrs | None": ...

    async def get_spatial_extent(
        self,
    ) -> "TwoDimensionalSpatialExtent | ThreeDimensionSpatialExtent | None": ...

    async def get_temporal_extent(self) -> "TemporalExtent | None": ...

    async def get_additional_extents(self) -> "list[AdditionalExtent] | None": ...
