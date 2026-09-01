"""Potto feature provider that uses the collection config as its store.

This is a simple provider intended mainly for using in tests.
"""

import dataclasses
import datetime as dt
import logging
from typing import (
    Any,
    Literal,
    Sequence,
    TYPE_CHECKING,
)

import pydantic
import pyproj
import shapely
import shapely.ops
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
from ...schemas.features import (
    Feature,
    PottoFeatureFilter,
)

if TYPE_CHECKING:
    from ...config import PottoSettings
    from ...schemas.collections import Collection

logger = logging.getLogger(__name__)


def _reproject_geometry(
    geometry: shapely.Geometry, source_crs: str, target_crs: str
) -> shapely.Geometry:
    if source_crs == target_crs:
        return geometry
    transformer = pyproj.Transformer.from_crs(source_crs, target_crs, always_xy=True)
    return shapely.ops.transform(transformer.transform, geometry)


async def _reproject_feature(feature: Feature, target_crs: str) -> Feature:
    if feature.crs == target_crs:
        return feature
    return dataclasses.replace(
        feature,
        geometry=_reproject_geometry(feature.geometry, feature.crs, target_crs),
        crs=target_crs,
    )


def _feature_matches_bbox(feature: Feature, feature_filter: PottoFeatureFilter) -> bool:
    if feature_filter.bbox_2d is None:
        return True
    bbox_geometry = _reproject_geometry(
        shapely.box(*feature_filter.bbox_2d), feature_filter.bbox_crs, feature.crs
    )
    return bbox_geometry.intersects(feature.geometry)


def _parse_datetime_range(value: str) -> tuple[dt.datetime | None, dt.datetime | None]:
    """Parse an RFC 3339 instant or interval into a (start, end) pair.

    Per OGC API - Features, an interval is two RFC 3339 datetimes separated by '/', where
    either side may be '..' for an open end; a bare value is a single instant, i.e. both
    ends of the range are that same instant.
    """
    if "/" in value:
        raw_start, raw_end = value.split("/", 1)
    else:
        raw_start = raw_end = value
    start = None if raw_start == ".." else dt.datetime.fromisoformat(raw_start)
    end = None if raw_end == ".." else dt.datetime.fromisoformat(raw_end)
    return start, end


def _feature_matches_datetime(
    feature: Feature, feature_filter: PottoFeatureFilter, datetime_field: str | None
) -> bool:
    if datetime_field is None or feature_filter.datetime_ is None:
        return True
    raw_value = feature.properties.get(datetime_field)
    if raw_value is None:
        return False
    value = (
        raw_value
        if isinstance(raw_value, dt.datetime)
        else dt.datetime.fromisoformat(str(raw_value))
    )
    start, end = _parse_datetime_range(feature_filter.datetime_)
    if start is not None and value < start:
        return False
    if end is not None and value > end:
        return False
    return True


def _feature_matches_filter(
    feature: Feature, feature_filter: PottoFeatureFilter, datetime_field: str | None
) -> bool:
    return _feature_matches_bbox(feature, feature_filter) and _feature_matches_datetime(
        feature, feature_filter, datetime_field
    )


def _match_features(
    all_features: Sequence[Feature],
    feature_filter: PottoFeatureFilter,
    datetime_field: str | None,
) -> list[Feature]:
    return [
        f
        for f in all_features
        if _feature_matches_filter(f, feature_filter, datetime_field)
    ]


async def _paginate_and_reproject(
    matched_features: Sequence[Feature], feature_filter: PottoFeatureFilter
) -> list[Feature]:
    page = matched_features[
        feature_filter.offset : feature_filter.offset + feature_filter.limit
    ]
    return [await _reproject_feature(f, feature_filter.crs) for f in page]


def _infer_property_schema(value: Any) -> JsonSchemaValue:
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, dt.datetime):
        return {"type": "string", "format": "date-time"}
    return {"type": "string"}


def _build_properties_schema(
    features: dict[str, Feature],
) -> dict[str, JsonSchemaValue]:
    properties: dict[str, JsonSchemaValue] = {}
    for feature in features.values():
        for name, value in feature.properties.items():
            if name not in properties and value is not None:
                properties[name] = _infer_property_schema(value)
    return properties


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
    datetime_field: str | None = None


class CollectionConfigFeatureProvider:
    """Read-only feature provider that stores features in the collection configuration."""

    collection: "Collection"
    config: CollectionConfigFeatureProviderConfiguration
    features: dict[str, Feature]

    def __init__(
        self,
        collection: "Collection",
        config: CollectionConfigFeatureProviderConfiguration,
    ) -> None:
        self.config = config
        self.collection = collection
        self.features = {
            i.id_: Feature(
                id_=i.id_,
                properties=i.properties.copy(),
                geometry=shapely.from_wkt(i.geometry),
                crs=self.config.storage_crs,
            )
            for i in self.config.raw_features
        }

    async def list_features(
        self,
        feature_filter: PottoFeatureFilter | None = None,
    ) -> list[Feature]:
        effective_filter = feature_filter or PottoFeatureFilter()
        matched = _match_features(
            list(self.features.values()), effective_filter, self.config.datetime_field
        )
        return await _paginate_and_reproject(matched, effective_filter)

    async def count_items(
        self, feature_filter: PottoFeatureFilter | None = None
    ) -> CountedItems:
        matched = _match_features(
            list(self.features.values()),
            feature_filter or PottoFeatureFilter(),
            self.config.datetime_field,
        )
        return CountedItems(total=len(self.features), matched=len(matched))

    async def get_feature(
        self,
        feature_id: str,
        crs: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
    ) -> Feature | None:
        if (feat := self.features.get(feature_id)) is None:
            return None
        if crs != feat.crs:
            return await _reproject_feature(feat, crs)
        return feat

    async def get_schema(self) -> JsonSchemaValue:
        title = (
            self.collection.title.get("en", "")  # TODO: localize this
            if isinstance(self.collection.title, dict)
            else self.collection.title
        )
        properties: dict[str, JsonSchemaValue] = {
            "id": {
                "type": "string",
                "x-ogc-role": "id",
            },
            "geometry": {
                "format": "geometry-any",
                "x-ogc-role": "primary-geometry",
            },
            **_build_properties_schema(self.features),
        }
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "title": title,
            "properties": properties,
        }

    async def get_queryables(self) -> JsonSchemaValue:
        properties: dict[str, JsonSchemaValue] = {
            "id": {"type": "string"},
            **_build_properties_schema(self.features),
        }
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "title": "Queryables",
            "properties": properties,
        }

    async def get_storage_crs(self) -> StorageCrs | None:
        return StorageCrs(crs=self.config.storage_crs)

    async def get_spatial_extent(
        self,
    ) -> TwoDimensionalSpatialExtent | ThreeDimensionSpatialExtent | None:
        if not self.features:
            return None
        minx, miny, maxx, maxy = shapely.total_bounds(
            [f.geometry for f in self.features.values()]
        )
        return TwoDimensionalSpatialExtent(
            bbox=[(float(minx), float(miny), float(maxx), float(maxy))],
            crs=self.config.storage_crs,
        )

    async def get_temporal_extent(self) -> TemporalExtent | None:
        if self.config.datetime_field is None:
            return None
        values: list[dt.datetime] = []
        for feature in self.features.values():
            raw_value = feature.properties.get(self.config.datetime_field)
            if raw_value is None:
                continue
            values.append(
                raw_value
                if isinstance(raw_value, dt.datetime)
                else dt.datetime.fromisoformat(str(raw_value))
            )
        if not values:
            return None
        return TemporalExtent(
            interval=[(min(values).isoformat(), max(values).isoformat())]
        )

    async def get_additional_extents(self) -> list[AdditionalExtent] | None:
        return None


async def collection_config_provider_factory(
    collection: "Collection",
    raw_config: dict[str, Any],
    potto_config: "PottoSettings",
) -> CollectionConfigFeatureProvider:
    config = CollectionConfigFeatureProviderConfiguration.model_validate(raw_config)
    return CollectionConfigFeatureProvider(collection, config)
