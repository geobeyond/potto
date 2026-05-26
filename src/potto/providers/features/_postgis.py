import logging
from typing import (
    Any,
    TYPE_CHECKING,
)

import pydantic
from geoalchemy2 import Geometry as _Geometry  # registers column_reflect listener
from geoalchemy2.shape import to_shape
from pydantic.json_schema import JsonSchemaValue
from sqlalchemy import (
    MetaData,
    Table,
    and_,
    func,
    select,
    types as sa_types,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    create_async_engine,
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
from ...schemas.potto import (
    Feature,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession
    from ...config import PottoSettings
    from ...schemas.potto import Collection

logger = logging.getLogger(__name__)

# TODO: cache reflected Table by (engine_url, schema, db_object)

_GEOM_TYPE_TO_FORMAT: dict[str, str] = {
    "POINT": "geometry-point",
    "MULTIPOINT": "geometry-multipoint",
    "LINESTRING": "geometry-linestring",
    "MULTILINESTRING": "geometry-multilinestring",
    "POLYGON": "geometry-polygon",
    "MULTIPOLYGON": "geometry-multipolygon",
    "GEOMETRYCOLLECTION": "geometry-geometrycollection",
    "GEOMETRY": "geometry-any",
}


def _parse_srid_from_crs_uri(uri: str) -> int:
    if uri.endswith("CRS84"):
        return 4326
    last_path_segment = uri.rstrip("/").rsplit("/", 1)[-1]
    try:
        return int(last_path_segment)
    except ValueError as exc:
        raise ValueError(f"Unsupported CRS URI: {uri!r}") from exc


def _format_srid_as_crs_uri(srid: int) -> str:
    return f"http://www.opengis.net/def/crs/EPSG/0/{srid}"


def _build_col_schema(col: Any) -> dict:
    column_type = col.type
    schema: dict
    if isinstance(column_type, _Geometry):
        geom_type = (getattr(column_type, "geometry_type", None) or "GEOMETRY").upper()
        schema = {
            "format": _GEOM_TYPE_TO_FORMAT.get(geom_type, "geometry-any"),
            "x-ogc-role": "primary-geometry",
        }
    elif isinstance(column_type, sa_types.Boolean):
        schema = {"type": "boolean"}
    elif isinstance(column_type, sa_types.Integer):
        schema = {"type": "integer"}
    elif isinstance(column_type, (sa_types.Float, sa_types.Numeric)):
        schema = {"type": "number"}
    elif isinstance(column_type, sa_types.DateTime):
        schema = {"type": "string", "format": "date-time"}
    elif isinstance(column_type, sa_types.Date):
        schema = {"type": "string", "format": "date"}
    elif isinstance(column_type, sa_types.Time):
        schema = {"type": "string", "format": "time"}
    elif isinstance(column_type, sa_types.Uuid):
        schema = {"type": "string", "format": "uuid"}
    elif isinstance(column_type, sa_types.LargeBinary):
        schema = {"type": "string", "contentEncoding": "base64"}
    elif isinstance(column_type, sa_types.JSON):
        schema = {}
    elif isinstance(column_type, (sa_types.String, sa_types.Text)):
        schema = {"type": "string"}
        if hasattr(column_type, "length") and column_type.length is not None:
            schema["maxLength"] = column_type.length
    else:
        schema = {"type": "string"}
    if col.comment:
        schema["description"] = col.comment
    return schema


def _build_ogc_schema(
    table: Table,
    id_column: str,
    geom_column: str,
    native_srid: int,
) -> JsonSchemaValue:
    properties: dict[str, Any] = {}
    properties[id_column] = {
        **_build_col_schema(table.c[id_column]),
        "x-ogc-role": "id",
    }
    geometry_column_schema = _build_col_schema(table.c[geom_column])
    if native_srid and native_srid != 4326:
        geometry_column_schema["x-ogc-srs"] = _format_srid_as_crs_uri(native_srid)
    properties[geom_column] = geometry_column_schema
    for col in table.columns:
        if col.name in (id_column, geom_column):
            continue
        properties[col.name] = _build_col_schema(col)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "title": table.name,
        "properties": properties,
    }


class PostgisFeatureProviderConfiguration(pydantic.BaseModel):
    db_dsn: str
    db_schema: str = "public"
    db_object: str
    geometry_column: str = "geom"
    id_column: str | None = None


class PostgisFeatureProvider:
    def __init__(self, config: PostgisFeatureProviderConfiguration):
        self.config = config
        self._engine: AsyncEngine = create_async_engine(config.db_dsn)
        self._table: Table | None = None
        self._id_column: str | None = None
        self._native_srid: int | None = None

    async def _ensure_reflected(self) -> None:
        if self._table is not None:
            return
        metadata = MetaData()
        async with self._engine.connect() as conn:
            await conn.run_sync(
                metadata.reflect,
                schema=self.config.db_schema,
                only=[self.config.db_object],
                views=True,
            )
        qualified_table_name = f"{self.config.db_schema}.{self.config.db_object}"
        table = metadata.tables[qualified_table_name]
        if self.config.id_column is not None:
            if self.config.id_column not in table.c:
                raise ValueError(
                    f"id_column {self.config.id_column!r} not found in {qualified_table_name}"
                )
            id_column = self.config.id_column
        else:
            primary_key_columns = list(table.primary_key.columns)
            if len(primary_key_columns) != 1:
                raise ValueError(
                    f"{qualified_table_name} has {len(primary_key_columns)} primary key column(s); "
                    f"set id_column explicitly in the provider config"
                )
            id_column = primary_key_columns[0].name
        geometry_column = table.c[self.config.geometry_column]
        self._table = table
        self._id_column = id_column
        self._native_srid = getattr(geometry_column.type, "srid", None) or 4326

    def _transform_geom_to_srid(self, target_srid: int) -> Any:
        assert self._table is not None and self._native_srid is not None
        geometry_column = self._table.c[self.config.geometry_column]
        if target_srid == self._native_srid:
            return geometry_column
        return func.ST_Transform(geometry_column, target_srid)

    def _build_select(
        self, *, target_srid: int, projection: list[str] | None = None
    ) -> Any:
        assert self._table is not None and self._id_column is not None
        geometry_column_name = self.config.geometry_column
        geometry_expression = self._transform_geom_to_srid(target_srid).label(
            geometry_column_name
        )
        non_geometry_columns = [
            c for c in self._table.columns if c.name != geometry_column_name
        ]
        if projection is not None:
            required_columns = set(projection) | {self._id_column}
            non_geometry_columns = [
                c for c in non_geometry_columns if c.name in required_columns
            ]
        return select(*non_geometry_columns, geometry_expression)

    def _apply_filter(self, stmt: Any, ff: PottoFeatureFilter) -> Any:
        assert self._table is not None and self._native_srid is not None
        where_clauses = []
        if ff.bbox is not None:
            bbox_srid = _parse_srid_from_crs_uri(ff.bbox_crs)
            bbox_envelope = func.ST_MakeEnvelope(*ff.bbox, bbox_srid)
            if bbox_srid != self._native_srid:
                bbox_envelope = func.ST_Transform(bbox_envelope, self._native_srid)
            where_clauses.append(
                func.ST_Intersects(
                    self._table.c[self.config.geometry_column], bbox_envelope
                )
            )
        # CQL2 hook: pygeofilter expressions land here
        if where_clauses:
            stmt = stmt.where(and_(*where_clauses))
        return stmt

    def _coerce_id(self, raw_id: str) -> Any:
        assert self._table is not None and self._id_column is not None
        primary_key_column = self._table.c[self._id_column]
        python_type = primary_key_column.type.python_type
        if python_type is str:
            return raw_id
        try:
            return python_type(raw_id)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"Cannot coerce {raw_id!r} to {python_type.__name__}"
            ) from exc

    def _build_feature_from_row(
        self,
        row_data: dict[str, Any],
        *,
        projection: list[str] | None = None,
    ) -> Feature:
        assert self._id_column is not None
        raw_geometry = row_data.pop(self.config.geometry_column, None)
        feature_id = row_data.pop(self._id_column, None)
        if projection is not None:
            row_data = {k: v for k, v in row_data.items() if k in projection}
        return Feature(
            id_=str(feature_id),
            properties=row_data,
            geometry=to_shape(raw_geometry) if raw_geometry is not None else None,
        )

    async def list_features(
        self, feature_filter: PottoFeatureFilter | None = None
    ) -> list[Feature]:
        await self._ensure_reflected()
        effective_filter = feature_filter or PottoFeatureFilter()
        stmt = self._build_select(
            target_srid=_parse_srid_from_crs_uri(effective_filter.crs),
            projection=effective_filter.properties,
        )
        stmt = self._apply_filter(stmt, effective_filter)
        stmt = stmt.limit(effective_filter.limit).offset(effective_filter.offset)
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
        return [
            self._build_feature_from_row(
                dict(row), projection=effective_filter.properties
            )
            for row in result.mappings()
        ]

    async def count_items(
        self, feature_filter: PottoFeatureFilter | None = None
    ) -> CountedItems:
        await self._ensure_reflected()
        assert self._table is not None
        effective_filter = feature_filter or PottoFeatureFilter()
        total_stmt = select(func.count()).select_from(self._table)
        async with self._engine.connect() as conn:
            total = (await conn.execute(total_stmt)).scalar_one()
            if effective_filter.bbox is None:
                return CountedItems(matched=total, total=total)
            matched_stmt = self._apply_filter(
                select(func.count()).select_from(self._table), effective_filter
            )
            matched = (await conn.execute(matched_stmt)).scalar_one()
        return CountedItems(matched=matched, total=total)

    async def get_feature(
        self,
        feature_id: str,
        crs: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
    ) -> Feature | None:
        await self._ensure_reflected()
        assert self._table is not None and self._id_column is not None
        primary_key_column = self._table.c[self._id_column]
        stmt = self._build_select(target_srid=_parse_srid_from_crs_uri(crs)).where(
            primary_key_column == self._coerce_id(feature_id)
        )
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
        matched_row = result.mappings().first()
        return self._build_feature_from_row(dict(matched_row)) if matched_row else None

    async def get_schema(self) -> JsonSchemaValue:
        await self._ensure_reflected()
        assert (
            self._table is not None
            and self._id_column is not None
            and self._native_srid is not None
        )
        return _build_ogc_schema(
            self._table, self._id_column, self.config.geometry_column, self._native_srid
        )

    async def get_queryables(self) -> JsonSchemaValue:
        await self._ensure_reflected()
        assert (
            self._table is not None
            and self._id_column is not None
            and self._native_srid is not None
        )
        return _build_ogc_schema(
            self._table, self._id_column, self.config.geometry_column, self._native_srid
        )

    async def get_storage_crs(self) -> StorageCrs | None:
        await self._ensure_reflected()
        if not self._native_srid:
            return None
        return StorageCrs(crs=_format_srid_as_crs_uri(self._native_srid))

    async def get_spatial_extent(
        self,
    ) -> TwoDimensionalSpatialExtent | ThreeDimensionSpatialExtent | None:
        await self._ensure_reflected()
        assert self._table is not None and self._native_srid is not None
        geometry_column = self._table.c[self.config.geometry_column]
        extent_subquery = select(
            func.ST_Extent(geometry_column).label("ext")
        ).subquery()
        stmt = select(
            func.ST_XMin(extent_subquery.c.ext),
            func.ST_YMin(extent_subquery.c.ext),
            func.ST_XMax(extent_subquery.c.ext),
            func.ST_YMax(extent_subquery.c.ext),
        )
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
        extent_row = result.one_or_none()
        if extent_row is None or extent_row[0] is None:
            return None
        xmin, ymin, xmax, ymax = (
            float(extent_row[0]),
            float(extent_row[1]),
            float(extent_row[2]),
            float(extent_row[3]),
        )
        return TwoDimensionalSpatialExtent(
            bbox=[(xmin, ymin, xmax, ymax)],
            crs=_format_srid_as_crs_uri(self._native_srid),
        )

    async def get_temporal_extent(self) -> TemporalExtent | None:
        return None

    async def get_additional_extents(self) -> list[AdditionalExtent] | None:
        return None


async def postgis_provider_factory(
    collection: "Collection",
    raw_config: dict[str, Any],
    session: "AsyncSession",
    potto_config: "PottoSettings",
) -> PostgisFeatureProvider:
    config = PostgisFeatureProviderConfiguration.model_validate(raw_config)
    return PostgisFeatureProvider(config)
