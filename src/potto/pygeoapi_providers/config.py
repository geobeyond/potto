import json
import logging
from typing import Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from pygeoapi.crs import CrsTransformSpec

import shapely
import shapely.strtree
import shapely.geometry
from pygeoapi.crs import crs_transform
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

    @crs_transform
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
        logger.debug(f"{locals()=}")
        features = list(self._data.values())
        if bbox:
            bbox_geom = _bbox_to_geometry(bbox)
            features = _perform_bbox_filtering(bbox_geom, features)
        num_matched = len(features)
        features = _perform_offset_limit_filtering(limit, offset, features)
        return GeoJsonFeatureCollection(
            {
                "type": "FeatureCollection",
                "features": features,
                "numberMatched": num_matched,
            }
        )

    @crs_transform
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

    @crs_transform
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
        if bbox:
            bbox_geom = _bbox_to_geometry(bbox)
            features = _perform_bbox_filtering(bbox_geom, features)
        num_matched = len(features)
        features = _perform_offset_limit_filtering(limit, offset, features)
        return GeoJsonFeatureCollection(
            {
                "type": "FeatureCollection",
                "features": features,
                "numberMatched": num_matched,
            }
        )

    @crs_transform
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


def _bbox_to_geometry(bbox: RawBbox) -> shapely.Geometry:
    """Convert a bbox to a shapely geometry, handling antimeridian crossing.

    When minX > maxX the bbox spans the antimeridian (lon=±180), so we union
    two boxes: one for each side of the antimeridian.
    """
    logger.debug(f"{bbox=}")
    minx, miny, maxx, maxy = bbox[0], bbox[1], bbox[2], bbox[3]
    if minx > maxx:
        return shapely.unary_union(
            [
                shapely.box(minx, miny, 180.0, maxy),
                shapely.box(-180.0, miny, maxx, maxy),
            ]
        )
    return shapely.box(minx, miny, maxx, maxy)


def _perform_offset_limit_filtering(
    limit: int,
    offset: int,
    features: list[GeoJsonFeature],
) -> list[GeoJsonFeature]:
    if offset > len(features) or limit <= 0:
        return []
    return features[max(offset, 0) : limit]


def _perform_bbox_filtering(
    bbox: shapely.Polygon, features: list[GeoJsonFeature], strtree_threshold: int = 1000
) -> list[GeoJsonFeature]:
    """Filter input features by checking intersection with a bounding box.

    The `strtree_threshold` parameter is used for deciding on the intersection
    algorithm to use. The intent here is to use a faster technique if there is
    a large number of input features.
    """
    no_geom_feats = [f for f in features if f.get("geometry") is None]
    geom_feats = [f for f in features if f.get("geometry") is not None]
    if len(geom_feats) < strtree_threshold:
        shapely.prepare(bbox)
        return [
            *no_geom_feats,
            *[
                feat
                for feat in geom_feats
                if bbox.intersects(shapely.geometry.shape(feat["geometry"]))
            ],
        ]
    else:
        geoms = [shapely.geometry.shape(feat["geometry"]) for feat in geom_feats]
        tree = shapely.strtree.STRtree(geoms)
        intersecting_indexes = tree.query(bbox, predicate="intersects")
        relevant_geom_feats = [geom_feats[i] for i in intersecting_indexes]
        return [
            *no_geom_feats,
            *relevant_geom_feats,
        ]


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
