import json
import logging
from typing import Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from pygeoapi.crs import CrsTransformSpec

import shapely
from pygeoapi.provider.base import ProviderItemNotFoundError

from .base import (
    CqlQueryText,
    EqualityFilterableProperty,
    GeoJsonFeature,
    GeoJsonFeatureCollection,
    RawBbox,
    RawDateTimeOrRange,
    RawFullTextSearchQuery,
    ReturnableProperty,
    SortByEntry,
)

logger = logging.getLogger(__name__)


class PygeoapiConfigWktFeatureProvider:
    _fields: dict[str, dict[str, str]]
    _data: dict[str, GeoJsonFeature]

    editable: bool = False
    id_field: str | None = None
    include_extra_query_parameters: bool = False
    properties: list[ReturnableProperty]
    storage_crs: str
    time_field: str | None = None
    type: str = "feature"
    uri_field: str | None = None

    def __init__(self, provider_definition: dict) -> None:
        self._data = {}
        for feat in provider_definition["data"].get("features", []):
            if (wkt_geom := feat.get("geometry")) or None is not None:
                feat_geom = shapely.from_wkt(wkt_geom)
                geojson_geom = json.loads(shapely.to_geojson(feat_geom))
            else:
                geojson_geom = None
            self._data[str(feat["id"])] = GeoJsonFeature(
                {
                    "type": "Feature",
                    "id": feat["id"],
                    "geometry": geojson_geom,
                    "properties": feat["properties"].copy(),
                }
            )
        self.storage_crs = provider_definition["data"].get(
            "crs", "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
        )
        try:
            first_feature = next(iter(self._data.values()))
        except StopIteration:
            self.properties = []
            self._fields = {}
            return

        self._fields = _get_fields(
            first_feature, provider_definition.get("properties") or []
        )
        self.properties = list(
            ReturnableProperty(prop_name) for prop_name in self._fields.keys()
        )

    @property
    def fields(self) -> dict:
        return self._fields.copy()

    def query(
        self,
        offset: int = 0,
        limit: int = 10,
        resulttype: Literal["hits", "results"] = "results",
        bbox: RawBbox | None = None,
        datetime_: RawDateTimeOrRange | None = None,
        properties: list[EqualityFilterableProperty] | None = None,
        sortby: list[SortByEntry] | None = None,
        skip_geometry: bool = False,
        select_properties: list[ReturnableProperty] | None = None,
        crs_transform_spec: "CrsTransformSpec | None" = None,
        q: RawFullTextSearchQuery | None = None,
        language: str | None = None,
        filterq: CqlQueryText | None = None,
    ) -> GeoJsonFeatureCollection:
        features = list(self._data.values())
        return GeoJsonFeatureCollection(
            {
                "type": "FeatureCollection",
                "features": features,
                "numberMatched": len(features),
            }
        )

    def get(
        self,
        identifier: str | int,
        crs_transform_spec: "CrsTransformSpec | None" = None,
        **kwargs,
    ) -> GeoJsonFeature:
        try:
            return GeoJsonFeature(self._data[str(identifier)].copy())
        except KeyError as err:
            raise ProviderItemNotFoundError(f"Item {identifier!r} not found") from err


class PygeoapiConfigGeoJsonFeatureProvider:
    _fields: dict[str, dict[str, str]]
    _data: dict[str, GeoJsonFeature]

    editable: bool = False
    id_field: str | None = None
    include_extra_query_parameters: bool = False
    properties: list[ReturnableProperty]
    storage_crs: str
    time_field: str | None = None
    type: str = "feature"
    uri_field: str | None = None

    def __init__(self, provider_definition: dict) -> None:
        """Pygeoapi provider that stores data directly in the configuration object.

        This is mainly useful for testing.
        """
        # TODO: let's check that data is valid GeoJSON and is a FeatureCollection
        self._data = {
            str(feat["id"]): feat
            for feat in provider_definition["data"].get("features", [])
        }
        self.storage_crs = provider_definition["data"].get(
            "crs", "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
        )
        try:
            first_feature = next(iter(self._data.values()))
        except StopIteration:
            self.properties = []
            self._fields = {}
            return

        self._fields = _get_fields(
            first_feature, provider_definition.get("properties") or []
        )
        self.properties = list(
            ReturnableProperty(prop_name) for prop_name in self._fields.keys()
        )

    @property
    def fields(self) -> dict:
        return self._fields.copy()

    def query(
        self,
        offset: int = 0,
        limit: int = 10,
        resulttype: Literal["hits", "results"] = "results",
        bbox: RawBbox | None = None,
        datetime_: RawDateTimeOrRange | None = None,
        properties: list[EqualityFilterableProperty] | None = None,
        sortby: list[SortByEntry] | None = None,
        skip_geometry: bool = False,
        select_properties: list[ReturnableProperty] | None = None,
        crs_transform_spec: "CrsTransformSpec | None" = None,
        q: RawFullTextSearchQuery | None = None,
        language: str | None = None,
        filterq: CqlQueryText | None = None,
    ) -> GeoJsonFeatureCollection:
        features = list(self._data.values())
        return GeoJsonFeatureCollection(
            {
                "type": "FeatureCollection",
                "features": features,
                "numberMatched": len(features),
            }
        )

    def get(
        self,
        identifier: str | int,
        crs_transform_spec: "CrsTransformSpec | None" = None,
        **kwargs,
    ) -> GeoJsonFeature:
        try:
            return GeoJsonFeature(self._data[str(identifier)].copy())
        except KeyError as err:
            raise ProviderItemNotFoundError(f"Item {identifier!r} not found") from err


def _get_fields(
    feature: GeoJsonFeature, returnable_properties: list[ReturnableProperty]
) -> dict:
    field_names = set(feature["properties"].keys())
    if len(returnable_properties) > 0:
        field_names = field_names.intersection(returnable_properties)
    field_schema = {}
    for name, value in feature["properties"].items():
        if name not in field_names:
            continue
        value_type = type(value).__name__
        try:
            schema_type = {
                "float": "number",
                "int": "integer",
                "bool": "boolean",
                "str": "string",
            }[value_type]
        except KeyError:
            logger.warning(f"Ignoring unsupported type {value_type}")
            continue
        field_schema[name] = {"type": schema_type}
    return field_schema
