import asyncio
import logging
import math
from typing import (
    Any,
    Literal,
)

import geopandas as gpd
import numpy as np
import pandas as pd
import pydantic
import pyogrio
from pydantic.json_schema import JsonSchemaValue
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import PottoSettings
from ...schemas.potto import Feature
from ...schemas.base import (
    CountedItems,
    PottoFeatureFilter,
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


def _dtype_to_json_schema(dtype: str) -> JsonSchemaValue:
    if dtype.startswith("datetime64"):
        return {"type": "string", "format": "date-time"}
    if dtype.startswith("date32") or dtype == "date":
        return {"type": "string", "format": "date"}
    return _DTYPE_TO_JSON_SCHEMA.get(dtype, {"type": "string"})


def _geometry_type_to_json_schema(geometry_type: str | None) -> JsonSchemaValue:
    # pyogrio can report "Point Z", "Polygon ZM", etc. — only the first token matters.
    # "Unknown" and None both fall back to geometry-any.
    base = (geometry_type or "").split(" ")[0]
    return {
        "x-ogc-role": "primary-geometry",
        "format": _GEOMETRY_TYPE_TO_FORMAT.get(base, "geometry-any"),
    }


def _coerce(value: Any) -> str | int | float | bool | None:
    """Convert numpy scalars to native Python types and NaN to None."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, np.generic):
        # np.int64 -> int, np.float64 -> float, np.bool_ -> bool, etc.
        native = value.item()
        if isinstance(native, float) and math.isnan(native):
            return None
        return native
    return value


def _series_to_feature(
    row: pd.Series,
    geom_col: str,
    id_value: Any,
    id_column: str | None = None,
) -> Feature:
    """Convert a single GeoDataFrame row (as a Series) into a Feature."""
    return Feature(
        id_=str(id_value),
        properties={
            str(name): _coerce(value)
            for name, value in row.items()
            if name != geom_col and name != id_column
        },
        geometry=row[geom_col],
    )


def _geodataframe_to_features(
    gdf: gpd.GeoDataFrame,
    id_column: str | None = None,
) -> list[Feature]:
    """Convert a GeoDataFrame into a list of Feature instances."""
    geom_col = str(gdf.geometry.name)
    return [
        _series_to_feature(
            row,
            geom_col=geom_col,
            id_value=index if id_column is None else row[id_column],
            id_column=id_column,
        )
        for index, row in gdf.iterrows()
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
    gdal_open_options: dict[str, str | int | bool] | None = None,
) -> list[Feature]:
    feats_df = pyogrio.read_dataframe(
        data_source_uri,
        max_features=item_filter.limit,
        skip_features=item_filter.offset,
        fid_as_index=id_column is None,
        where=_build_where_clause(item_filter),
        bbox=item_filter.bbox,
        **(gdal_open_options or {}),
    )
    return _geodataframe_to_features(feats_df, id_column=id_column)


def _count_features(
    data_source_uri: str,
    feature_filter: PottoFeatureFilter | None = None,
) -> CountedItems:
    info = pyogrio.read_info(data_source_uri)
    total = info["features"]
    if feature_filter is None:
        return CountedItems(matched=total, total=total)
    where_clause = _build_where_clause(feature_filter)
    df = pyogrio.read_dataframe(
        data_source_uri,
        read_geometry=False,
        columns=[],
        where=where_clause,
        bbox=feature_filter.bbox,
    )
    return CountedItems(matched=len(df), total=total)


def _get_schema(
    data_source_uri: str,
    id_column: str | None = None,
) -> JsonSchemaValue:
    info = pyogrio.read_info(data_source_uri)
    geom_col = info["geometry_name"] or "geometry"
    skip = {f for f in (geom_col, id_column) if f}
    field_dtypes = dict(zip(info["fields"], info["dtypes"]))
    properties: dict[str, JsonSchemaValue] = {}
    if id_column is not None:
        properties[id_column] = {
            **_dtype_to_json_schema(field_dtypes.get(id_column, "object")),
            "x-ogc-role": "id",
        }
    properties[geom_col] = _geometry_type_to_json_schema(info["geometry_type"])
    properties.update(
        {
            field: _dtype_to_json_schema(dtype)
            for field, dtype in zip(info["fields"], info["dtypes"])
            if field not in skip
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
) -> Feature | None:
    info = pyogrio.read_info(data_source_uri)
    geom_col = info["geometry_name"] or "geometry"
    if id_column is None:  # id is the OGR FID
        try:
            fid = int(feature_id)
        except ValueError:
            return None
        gdf = pyogrio.read_dataframe(data_source_uri, fids=[fid], fid_as_index=True)
    else:  # id is column value, select via OGR's SQL layer
        escaped = feature_id.replace("'", "''")
        gdf = pyogrio.read_dataframe(
            data_source_uri, where=f"{id_column} = '{escaped}'"
        )
    if gdf.empty:
        return None
    row = gdf.iloc[0]
    index = gdf.index[0]
    return _series_to_feature(
        row,
        geom_col=geom_col,
        id_value=index if id_column is None else row[id_column],
        id_column=id_column,
    )


class PyogrioCsvGdalOpenOption(pydantic.BaseModel):
    driver_name: Literal["csv"]
    separator: Literal["AUTO", "COMMA", "SEMICOLLON", "TAB", "SPACE", "PIPE"] = "AUTO"
    keep_source_columns: bool = False
    x_possible_names: list[str] | None = None
    y_possible_names: list[str] | None = None
    z_possible_names: list[str] | None = None
    geom_possible_names: list[str] | None = None


class PyogrioFeatureProviderConfiguration(pydantic.BaseModel):
    provider_name: Literal["pyogrio"] = "pyogrio"
    data_source_uri: str
    id_column: str | None = None
    gdal_open_options: PyogrioCsvGdalOpenOption | None = None


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
        filter_ = feature_filter or PottoFeatureFilter(
            limit=self.potto_config.page_size,
        )
        return await asyncio.to_thread(
            _list_features, self.config.data_source_uri, filter_, self.config.id_column
        )

    async def count_items(
        self, feature_filter: PottoFeatureFilter | None = None
    ) -> CountedItems:
        return await asyncio.to_thread(
            _count_features, self.config.data_source_uri, feature_filter
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
        )

    async def get_schema(self) -> JsonSchemaValue:
        return await asyncio.to_thread(
            _get_schema,
            self.config.data_source_uri,
            self.config.id_column,
        )


def pyogrio_provider_factory(
    raw_config: dict[str, Any], session: AsyncSession, potto_config: PottoSettings
) -> PyogrioFeatureProvider:
    config = PyogrioFeatureProviderConfiguration.model_validate(raw_config)
    return PyogrioFeatureProvider(config, potto_config)
