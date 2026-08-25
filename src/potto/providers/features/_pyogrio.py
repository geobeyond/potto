import asyncio
import datetime as dt
import logging
import math
from typing import (
    Annotated,
    Any,
    Literal,
    Protocol,
)

import geopandas as gpd
import numpy as np
import pandas as pd
import pydantic
import pyogrio
import pyogrio.errors
import pyproj
from pydantic.json_schema import JsonSchemaValue

from ...config import PottoSettings
from ...schemas.potto import (
    Collection,
    Feature,
)
from ...schemas.base import (
    AdditionalExtent,
    CountedItems,
    PottoFeatureFilter,
    StorageCrs,
    TemporalExtent,
    ThreeDimensionSpatialExtent,
    TwoDimensionalSpatialExtent,
)

logger = logging.getLogger(__name__)


_DTYPE_TO_JSON_SCHEMA: dict[str, JsonSchemaValue] = {
    "int8": {"type": "integer"},
    "int16": {"type": "integer"},
    "int32": {"type": "integer"},
    "int64": {"type": "integer"},
    "uint8": {"type": "integer"},
    "uint16": {"type": "integer"},
    "uint32": {"type": "integer"},
    "uint64": {"type": "integer"},
    "float32": {"type": "number"},
    "float64": {"type": "number"},
    "bool": {"type": "boolean"},
    "object": {"type": "string"},
    "string": {"type": "string"},
}


_GEOMETRY_TYPE_TO_FORMAT: dict[str, str] = {
    "Point": "geometry-point",
    "MultiPoint": "geometry-multipoint",
    "LineString": "geometry-linestring",
    "MultiLineString": "geometry-multilinestring",
    "Polygon": "geometry-polygon",
    "MultiPolygon": "geometry-multipolygon",
    "GeometryCollection": "geometry-geometrycollection",
}


class SupportsReadDataframeKwargs(Protocol):
    def as_read_dataframe_kwargs(self) -> dict[str, str]: ...


class PyogrioCsvGdalOpenOption(pydantic.BaseModel):
    driver_name: Literal["CSV"] = "CSV"
    autodetect_type: bool = True
    separator: Literal["AUTO", "COMMA", "SEMICOLON", "TAB", "SPACE", "PIPE"] = "AUTO"
    keep_source_columns: bool = False
    keep_geom_columns: bool = False
    x_possible_names: list[str] | None = pydantic.Field(
        default_factory=lambda: ["lon*"]
    )
    y_possible_names: list[str] | None = pydantic.Field(
        default_factory=lambda: ["lat*"]
    )
    z_possible_names: list[str] | None = None
    geom_possible_names: list[str] | None = pydantic.Field(
        default_factory=lambda: ["wkt*"]
    )

    def as_read_dataframe_kwargs(self) -> dict[str, str]:
        return {
            option_name: option_value
            for option_name, option_value in {
                "AUTODETECT_TYPE": "YES" if self.autodetect_type else "NO",
                "SEPARATOR": self.separator,
                "KEEP_SOURCE_COLUMNS": "YES" if self.keep_source_columns else "NO",
                "KEEP_GEOM_COLUMNS": "YES" if self.keep_geom_columns else "NO",
                "X_POSSIBLE_NAMES": ",".join(self.x_possible_names)
                if self.x_possible_names
                else None,
                "Y_POSSIBLE_NAMES": ",".join(self.y_possible_names)
                if self.y_possible_names
                else None,
                "Z_POSSIBLE_NAMES": ",".join(self.z_possible_names)
                if self.z_possible_names
                else None,
                "GEOM_POSSIBLE_NAMES": ",".join(self.geom_possible_names)
                if self.geom_possible_names
                else None,
            }.items()
            if option_value is not None
        }


class PyogrioGeoJsonGdalOpenOption(pydantic.BaseModel):
    driver_name: Literal["GeoJSON"] = "GeoJSON"
    flatten_nested_attributes: bool = True
    nested_attribute_separator: str = "__"
    foreign_members: Literal["AUTO", "ALL", "NONE", "STAC"] = "AUTO"

    def as_read_dataframe_kwargs(self) -> dict[str, str]:
        return {
            "FLATTEN_NESTED_ATTRIBUTES": "YES"
            if self.flatten_nested_attributes
            else "NO",
            "NESTED_ATTRIBUTE_SEPARATOR": self.nested_attribute_separator,
            "FOREIGN_MEMBERS": self.foreign_members,
        }


GdalOpenOptions = PyogrioCsvGdalOpenOption | PyogrioGeoJsonGdalOpenOption


def _map_dtype_to_json_schema(dtype: str) -> JsonSchemaValue:
    if dtype.startswith("datetime64"):
        return {"type": "string", "format": "date-time"}
    if dtype.startswith("date32") or dtype == "date":
        return {"type": "string", "format": "date"}
    return _DTYPE_TO_JSON_SCHEMA.get(dtype, {"type": "string"})


def _map_geometry_type_to_json_schema(geometry_type: str | None) -> JsonSchemaValue:
    # pyogrio can report "Point Z", "Polygon ZM", etc. — only the first token matters.
    # "Unknown" and None both fall back to geometry-any.
    base_geometry_type = (geometry_type or "").split(" ")[0]
    return {
        "x-ogc-role": "primary-geometry",
        "format": _GEOMETRY_TYPE_TO_FORMAT.get(base_geometry_type, "geometry-any"),
    }


def _coerce_value(value: Any) -> str | int | float | bool | dt.datetime | None:
    """Convert numpy scalars to native Python types and NaN to None."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, np.generic):
        # np.int64 -> int, np.float64 -> float, np.bool_ -> bool, etc.
        native = value.item()
        if isinstance(native, float) and math.isnan(native):
            return None
        return native
    return value


def _build_feature_from_series(
    row: pd.Series,
    geom_col: str,
    id_value: Any,
    id_column: str | None = None,
) -> Feature:
    """Convert a single GeoDataFrame row (as a Series) into a Feature."""
    return Feature(
        id_=str(id_value),
        properties={
            str(name): _coerce_value(value)
            for name, value in row.items()
            if name != geom_col and name != id_column
        },
        geometry=row[geom_col],
    )


def _build_features_from_geodataframe(
    geodataframe: gpd.GeoDataFrame,
    id_column: str | None = None,
) -> list[Feature]:
    """Convert a GeoDataFrame into a list of Feature instances."""
    geom_col = str(geodataframe.geometry.name)
    return [
        _build_feature_from_series(
            row,
            geom_col=geom_col,
            id_value=index if id_column is None else row[id_column],
            id_column=id_column,
        )
        for index, row in geodataframe.iterrows()
    ]


def _build_where_clause(item_filter: PottoFeatureFilter) -> str | None:
    """Return an OGR SQL WHERE clause string, or None when there is nothing to filter.

    bbox is passed to pyogrio natively; limit/offset are pagination; properties
    is column selection — none of those belong here.  This function exists as
    the single place to compose future filter conditions (datetime, CQL2 text,
    property-value pairs, etc.) into an AND-joined expression.
    """
    parts: list[str] = []
    # future conditions: append to `parts`, e.g.
    #   if item_filter.datetime:
    #       parts.append(f"datetime >= '{item_filter.datetime.start}'")
    return " AND ".join(parts) if parts else None


def _list_features(
    data_source_uri: str,
    item_filter: PottoFeatureFilter,
    id_column: str | None = None,
    gdal_open_options: SupportsReadDataframeKwargs | None = None,
) -> list[Feature]:
    features_gdf = pyogrio.read_dataframe(
        data_source_uri,
        max_features=item_filter.limit,
        skip_features=item_filter.offset,
        fid_as_index=id_column is None,
        where=_build_where_clause(item_filter),
        bbox=item_filter.bbox_2d,
        **(gdal_open_options.as_read_dataframe_kwargs() if gdal_open_options else {}),
    )
    target_crs = pyproj.CRS(item_filter.crs)
    if features_gdf.crs is not None and not features_gdf.crs.equals(target_crs):
        features_gdf = features_gdf.to_crs(target_crs)
    return _build_features_from_geodataframe(features_gdf, id_column=id_column)


def _count_features(
    data_source_uri: str,
    feature_filter: PottoFeatureFilter | None = None,
    gdal_open_options: SupportsReadDataframeKwargs | None = None,
) -> CountedItems:
    info = pyogrio.read_info(data_source_uri)
    total = info["features"]
    if feature_filter is None:
        return CountedItems(matched=total, total=total)
    where_clause = _build_where_clause(feature_filter)
    matched_gdf = pyogrio.read_dataframe(
        data_source_uri,
        read_geometry=False,
        fid_as_index=True,
        columns=[],
        where=where_clause,
        bbox=feature_filter.bbox_2d,
        **(gdal_open_options.as_read_dataframe_kwargs() if gdal_open_options else {}),
    )
    return CountedItems(matched=len(matched_gdf), total=total)


def _get_schema(
    data_source_uri: str,
    id_column: str | None = None,
    gdal_open_options: SupportsReadDataframeKwargs | None = None,
) -> JsonSchemaValue:
    info = pyogrio.read_info(
        data_source_uri,
        **(gdal_open_options.as_read_dataframe_kwargs() if gdal_open_options else {}),
    )
    geom_col = info["geometry_name"] or "geometry"
    excluded_fields = {field for field in (geom_col, id_column) if field}
    field_dtypes = dict(zip(info["fields"], info["dtypes"]))
    properties: dict[str, JsonSchemaValue] = {}
    if id_column is not None:
        properties[id_column] = {
            **_map_dtype_to_json_schema(field_dtypes.get(id_column, "object")),
            "x-ogc-role": "id",
        }
    properties[geom_col] = _map_geometry_type_to_json_schema(info["geometry_type"])
    properties.update(
        {
            field: _map_dtype_to_json_schema(dtype)
            for field, dtype in zip(info["fields"], info["dtypes"])
            if field not in excluded_fields
        }
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "title": info["layer_name"],
        "properties": properties,
    }


def _get_feature(
    data_source_uri: str,
    feature_id: str,
    id_column: str | None = None,
    crs: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
    gdal_open_options: SupportsReadDataframeKwargs | None = None,
) -> Feature | None:
    info = pyogrio.read_info(
        data_source_uri,
        **(gdal_open_options.as_read_dataframe_kwargs() if gdal_open_options else {}),
    )
    geom_col = info["geometry_name"] or "geometry"
    if id_column is None:  # id is the OGR FID
        try:
            fid = int(feature_id)
        except ValueError:
            return None
        try:
            result_gdf = pyogrio.read_dataframe(
                data_source_uri,
                fids=[fid],
                fid_as_index=True,
                **(
                    gdal_open_options.as_read_dataframe_kwargs()
                    if gdal_open_options
                    else {}
                ),
            )
        except pyogrio.errors.FeatureError:
            logger.debug(f"FID {fid} not found in {data_source_uri}")
            return None
    else:  # id is column value, select via OGR's SQL layer
        escaped = feature_id.replace("'", "''")
        result_gdf = pyogrio.read_dataframe(
            data_source_uri,
            where=f"{id_column} = '{escaped}'",
            **(
                gdal_open_options.as_read_dataframe_kwargs()
                if gdal_open_options
                else {}
            ),
        )
    if result_gdf.empty:
        return None
    target_crs = pyproj.CRS(crs)
    if result_gdf.crs is not None and not result_gdf.crs.equals(target_crs):
        result_gdf = result_gdf.to_crs(target_crs)
    row = result_gdf.iloc[0]
    index = result_gdf.index[0]
    return _build_feature_from_series(
        row,
        geom_col=geom_col,
        id_value=index if id_column is None else row[id_column],
        id_column=id_column,
    )


def _format_crs_as_uri(authority: tuple[str, str] | None) -> str | None:
    if authority is None:
        return None
    authority_name, authority_code = authority
    if authority_name == "OGC":
        return f"http://www.opengis.net/def/crs/OGC/1.3/{authority_code}"
    return f"http://www.opengis.net/def/crs/{authority_name}/0/{authority_code}"


def _get_storage_crs(
    data_source_uri: str,
    gdal_open_options: SupportsReadDataframeKwargs | None = None,
) -> StorageCrs | None:
    info = pyogrio.read_info(
        data_source_uri,
        **(gdal_open_options.as_read_dataframe_kwargs() if gdal_open_options else {}),
    )
    if (raw_crs := info.get("crs")) is None:
        return None
    if (crs_uri := _format_crs_as_uri(pyproj.CRS(raw_crs).to_authority())) is None:
        return None
    return StorageCrs(crs=crs_uri)


def _get_spatial_extent(
    data_source_uri: str,
    gdal_open_options: SupportsReadDataframeKwargs | None = None,
) -> TwoDimensionalSpatialExtent | None:
    info = pyogrio.read_info(
        data_source_uri,
        **(gdal_open_options.as_read_dataframe_kwargs() if gdal_open_options else {}),
    )
    if (bounds := info.get("total_bounds")) is None:
        return None
    if (raw_crs := info.get("crs")) is None:
        return None
    if (crs_uri := _format_crs_as_uri(pyproj.CRS(raw_crs).to_authority())) is None:
        return None
    return TwoDimensionalSpatialExtent(
        bbox=[(float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))],
        crs=crs_uri,
    )


class PyogrioFeatureProviderConfiguration(pydantic.BaseModel):
    data_source_uri: str
    id_column: str | None = None
    gdal_open_options: Annotated[
        GdalOpenOptions | None, pydantic.Field(discriminator="driver_name")
    ] = None


class PyogrioFeatureProvider:
    config: PyogrioFeatureProviderConfiguration
    potto_config: PottoSettings

    def __init__(
        self, config: PyogrioFeatureProviderConfiguration, potto_config: PottoSettings
    ):
        """A feature provider that uses pyogrio to retrieve data.

        Note that pyogrio is not an async library. This implementation
        simply wraps it with calls to asyncio.to_thread.
        """
        self.config = config
        self.potto_config = potto_config

    async def list_features(
        self, feature_filter: PottoFeatureFilter | None = None
    ) -> list[Feature]:
        resolved_filter = feature_filter or PottoFeatureFilter(
            limit=self.potto_config.page_size,
        )
        return await asyncio.to_thread(
            _list_features,
            self.config.data_source_uri,
            resolved_filter,
            self.config.id_column,
            gdal_open_options=self.config.gdal_open_options,
        )

    async def count_items(
        self, feature_filter: PottoFeatureFilter | None = None
    ) -> CountedItems:
        return await asyncio.to_thread(
            _count_features,
            self.config.data_source_uri,
            feature_filter,
            gdal_open_options=self.config.gdal_open_options,
        )

    async def get_feature(
        self,
        feature_id: str,
        crs: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
    ) -> Feature | None:
        return await asyncio.to_thread(
            _get_feature,
            self.config.data_source_uri,
            feature_id,
            self.config.id_column,
            crs,
            gdal_open_options=self.config.gdal_open_options,
        )

    async def get_schema(self) -> JsonSchemaValue:
        return await asyncio.to_thread(
            _get_schema,
            self.config.data_source_uri,
            self.config.id_column,
            gdal_open_options=self.config.gdal_open_options,
        )

    async def get_queryables(self) -> JsonSchemaValue:
        return await asyncio.to_thread(
            _get_schema,
            self.config.data_source_uri,
            self.config.id_column,
            gdal_open_options=self.config.gdal_open_options,
        )

    async def get_storage_crs(self) -> StorageCrs | None:
        return await asyncio.to_thread(
            _get_storage_crs,
            self.config.data_source_uri,
            gdal_open_options=self.config.gdal_open_options,
        )

    async def get_spatial_extent(
        self,
    ) -> TwoDimensionalSpatialExtent | ThreeDimensionSpatialExtent | None:
        return await asyncio.to_thread(
            _get_spatial_extent,
            self.config.data_source_uri,
            gdal_open_options=self.config.gdal_open_options,
        )

    async def get_temporal_extent(self) -> TemporalExtent | None:
        return None

    async def get_additional_extents(self) -> list[AdditionalExtent] | None:
        return None


def pyogrio_provider_factory(
    collection: Collection,
    raw_config: dict[str, Any],
    potto_config: PottoSettings,
) -> PyogrioFeatureProvider:
    config = PyogrioFeatureProviderConfiguration.model_validate(raw_config)
    return PyogrioFeatureProvider(config, potto_config)
