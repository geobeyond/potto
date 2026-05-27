"""DuckDB feature provider for potto.

Reads features from any DuckDB-accessible source — GeoParquet on local disk or
S3-compatible object storage, CSV, JSON, attached PostgreSQL/SQLite databases, or
any SQL expression DuckDB can evaluate.  Read-only; implements FeatureProviderProtocol.

Concurrency model
-----------------
One DuckDB in-memory connection is opened per provider instance and held for its
lifetime.  Each async method dispatches sync DuckDB work via ``asyncio.to_thread``;
within that thread a fresh cursor is used so concurrent requests don't contend on
the same cursor object.  DuckDB itself is thread-safe and supports concurrent
queries against a shared connection.

Provider caching
----------------
# TODO: A new DuckdbFeatureProvider is created for every request because the
# registry does not cache provider instances.  This means DuckDB setup (extension
# loading, CREATE SECRET, ATTACH, schema probing) runs on every request, which is
# expensive — especially for S3-backed Parquet sources.  A registry-level cache
# keyed by (collection_identifier, config_hash) is required for production use and
# should be designed to cover all provider types, not just DuckDB.
"""

import asyncio
import logging
from typing import (
    Annotated,
    Any,
    Literal,
    TYPE_CHECKING,
)

import duckdb
import pydantic
import shapely
from pydantic.json_schema import JsonSchemaValue

from ...constants import CRS_84
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

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession
    from ...config import PottoSettings
    from ...schemas.potto import Collection

logger = logging.getLogger(__name__)


def _parse_srid_from_crs_uri(uri: str) -> int:
    """Parse an OGC CRS URI to an integer SRID.

    Handles both the ``CRS84`` / ``CRS84h`` special cases (→ 4326) and the
    numeric tail of EPSG authority URIs.
    """
    tail = uri.rstrip("/").rsplit("/", 1)[-1]
    if tail in ("CRS84", "CRS84h"):
        return 4326
    try:
        return int(tail)
    except ValueError as exc:
        raise ValueError(f"Unsupported CRS URI: {uri!r}") from exc


def _format_srid_as_crs_uri(srid: int) -> str:
    """Return the OGC CRS URI for the given SRID."""
    if srid == 4326:
        return CRS_84
    return f"http://www.opengis.net/def/crs/EPSG/0/{srid}"


def _quote_ident(name: str) -> str:
    """DuckDB identifier quoting: double-quotes with embedded double-quotes escaped."""
    return '"' + name.replace('"', '""') + '"'


def _quote_string_literal(value: str) -> str:
    """DuckDB string-literal quoting: single-quotes with embedded single-quotes escaped."""
    return "'" + value.replace("'", "''") + "'"


def _format_srid_as_epsg_string(srid: int) -> str:
    """Return a CRS identifier string for use in DuckDB ST_Transform calls.

    DuckDB spatial's ``ST_Transform`` takes string CRS identifiers (e.g.
    ``'EPSG:4326'``) rather than integer SRIDs.  This helper produces the
    correctly formatted identifier; the result must be embedded as a SQL
    string literal in the query.
    """
    return f"EPSG:{srid}"


def _format_as_iso_string(value: Any) -> str | None:
    """Convert a datetime/date/time value (or None) to an ISO 8601 string."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


class SecretSpec(pydantic.BaseModel):
    """A DuckDB named secret (e.g. S3 credentials)."""

    name: str
    type: str  # e.g. "S3"
    parameters: dict[str, str]  # KEY_ID, SECRET, ENDPOINT, URL_STYLE, REGION, …


class AttachSpec(pydantic.BaseModel):
    """A database to attach to the DuckDB connection."""

    target: str  # connection string, e.g. "postgresql://…"
    alias: str
    read_only: bool = True
    type: str | None = None  # e.g. "POSTGRES", "SQLITE"; DuckDB usually infers


class DuckdbFeatureProviderConfiguration(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    provider_name: Literal["duckdb"] = "duckdb"

    source: Annotated[
        str,
        pydantic.Field(
            description=(
                "SQL expression that yields the feature rows.  Examples: "
                "read_parquet('s3://bucket/path/file.parquet'), "
                "read_parquet('s3://bucket/path/**/*.parquet', hive_partitioning=true), "
                "my_attached_db.public.my_table, "
                "(SELECT * FROM raw_table WHERE active = true).  "
                "Treated as operator-controlled (config-file) input; user request "
                "data must never be interpolated into this value."
            )
        ),
    ]

    geometry_column: str = "geom"
    id_column: str  # no PK concept in arbitrary DuckDB sources

    extensions: list[str] = pydantic.Field(
        default_factory=lambda: ["spatial"],
        description=(
            "Extensions to INSTALL+LOAD at startup.  ``httpfs`` is added "
            "automatically when any secret of type S3 is declared."
        ),
    )

    secrets: list[SecretSpec] | None = None
    attach: list[AttachSpec] | None = None

    storage_crs: Annotated[
        str | None,
        pydantic.Field(
            description=(
                "Override CRS detection.  Useful for non-Parquet sources where "
                "ST_SRID cannot be relied upon (returns 0 for many GeoParquet files "
                "because CRS is encoded in file metadata rather than per-geometry)."
            )
        ),
    ] = None

    temporal_column: Annotated[
        str | None,
        pydantic.Field(
            description="Single datetime column used to compute the temporal extent."
        ),
    ] = None

    temporal_interval_columns: Annotated[
        tuple[str, str] | None,
        pydantic.Field(
            description="(start_column, end_column) pair for interval-based temporal extent."
        ),
    ] = None


_INTEGER_TYPES: frozenset[str] = frozenset(
    {
        "TINYINT",
        "INT1",
        "SMALLINT",
        "INT2",
        "SHORT",
        "INTEGER",
        "INT4",
        "INT",
        "SIGNED",
        "BIGINT",
        "INT8",
        "LONG",
        "HUGEINT",
        "UHUGEINT",
        "UTINYINT",
        "USMALLINT",
        "UINTEGER",
        "UBIGINT",
    }
)

_FLOAT_TYPES: frozenset[str] = frozenset(
    {
        "FLOAT",
        "FLOAT4",
        "REAL",
        "DOUBLE",
        "FLOAT8",
        "DOUBLE PRECISION",
    }
)

_STRING_TYPES: frozenset[str] = frozenset(
    {
        "VARCHAR",
        "TEXT",
        "STRING",
        "CHAR",
        "BPCHAR",
    }
)

_TIMESTAMP_TYPES: frozenset[str] = frozenset(
    {
        "TIMESTAMP",
        "TIMESTAMP WITH TIME ZONE",
        "TIMESTAMPTZ",
        "TIMESTAMP_S",
        "TIMESTAMP_MS",
        "TIMESTAMP_NS",
    }
)

_GEOMETRY_TYPE_TO_FORMAT: dict[str, str] = {
    "POINT": "geometry-point",
    "MULTIPOINT": "geometry-multipoint",
    "LINESTRING": "geometry-linestring",
    "MULTILINESTRING": "geometry-multilinestring",
    "POLYGON": "geometry-polygon",
    "MULTIPOLYGON": "geometry-multipolygon",
    "GEOMETRYCOLLECTION": "geometry-geometrycollection",
    "GEOMETRY": "geometry-any",
}


def _map_duckdb_type_to_json_schema(type_str: str) -> dict[str, Any]:
    """Map a DuckDB column type string to a JSON Schema fragment."""
    normalized_type = type_str.upper().strip()

    if normalized_type in _INTEGER_TYPES:
        return {"type": "integer"}

    if normalized_type in _FLOAT_TYPES:
        return {"type": "number"}

    if normalized_type.startswith("DECIMAL") or normalized_type.startswith("NUMERIC"):
        return {"type": "number"}

    if (
        normalized_type in _STRING_TYPES
        or normalized_type.startswith("VARCHAR(")
        or normalized_type.startswith("CHAR(")
    ):
        return {"type": "string"}

    if normalized_type in ("BOOLEAN", "BOOL", "LOGICAL"):
        return {"type": "boolean"}

    if normalized_type == "UUID":
        return {"type": "string", "format": "uuid"}

    if normalized_type == "DATE":
        return {"type": "string", "format": "date"}

    if normalized_type.startswith("TIME") and "STAMP" not in normalized_type:
        # TIME, TIME WITH TIME ZONE, TIMETZ — but not TIMESTAMP*
        return {"type": "string", "format": "time"}

    if normalized_type in _TIMESTAMP_TYPES or (
        normalized_type.startswith("TIMESTAMP") and normalized_type != "TIMESTAMP_TZ"
    ):
        return {"type": "string", "format": "date-time"}

    if normalized_type == "INTERVAL":
        return {"type": "string"}  # ISO 8601 duration

    if normalized_type in ("BLOB", "BYTEA", "BINARY", "VARBINARY"):
        return {"type": "string", "contentEncoding": "base64"}

    if normalized_type == "JSON":
        return {}

    if normalized_type == "GEOMETRY":
        # Handled separately by _build_geometry_column_schema; fallback if reached here.
        return {"type": "object", "format": "geometry"}

    # LIST / array types: INTEGER[] or INTEGER[n] or LIST(INTEGER)
    if "[" in normalized_type:
        element_type = normalized_type[: normalized_type.index("[")].strip()
        return {"type": "array", "items": _map_duckdb_type_to_json_schema(element_type)}
    if normalized_type.startswith("LIST(") and normalized_type.endswith(")"):
        element_type = normalized_type[5:-1].strip()
        return {"type": "array", "items": _map_duckdb_type_to_json_schema(element_type)}

    # STRUCT — basic fallback; full recursive parsing deferred
    if normalized_type.startswith("STRUCT("):
        return {"type": "object"}

    # MAP(KEY_TYPE, VALUE_TYPE)
    if normalized_type.startswith("MAP(") and normalized_type.endswith(")"):
        type_arguments = normalized_type[4:-1]
        type_parts = type_arguments.split(",", 1)
        if len(type_parts) == 2:
            return {
                "type": "object",
                "additionalProperties": _map_duckdb_type_to_json_schema(
                    type_parts[1].strip()
                ),
            }
        return {"type": "object"}

    logger.debug("Unknown DuckDB type %r — mapping to empty JSON Schema", type_str)
    return {}


class DuckdbFeatureProvider:
    """Read-only feature provider backed by a DuckDB in-memory connection.

    ``__init__`` is synchronous and performs all eager setup (extension loading,
    secret creation, database attachment, column probing).  The async factory
    wraps construction in ``asyncio.to_thread`` so setup does not block the
    event loop.
    """

    def __init__(
        self,
        config: DuckdbFeatureProviderConfiguration,
        potto_config: "PottoSettings",
    ) -> None:
        self.config = config
        self.potto_config = potto_config

        self._conn = duckdb.connect(":memory:")
        self._setup_connection()
        self._columns: list[tuple[str, str]] = self._describe_source_columns()
        self._validate_columns()

        # Per-instance lazy caches — populated on first use.
        self._cached_native_srid: int | None = None
        self._cached_spatial_extent: (
            TwoDimensionalSpatialExtent | ThreeDimensionSpatialExtent | None
        ) = None
        self._cached_temporal_extent: TemporalExtent | None = None
        self._cached_storage_crs: StorageCrs | None = None

    def _setup_connection(self) -> None:
        """Install/load extensions, create secrets, and attach external databases."""
        extensions = list(self.config.extensions)
        if self.config.secrets and any(
            secret.type.upper() == "S3" for secret in self.config.secrets
        ):
            if "httpfs" not in [
                extension_name.lower() for extension_name in extensions
            ]:
                extensions.append("httpfs")

        for extension_name in extensions:
            # Extension names are simple identifiers from operator config;
            # no quoting needed and quoting may break INSTALL/LOAD syntax.
            self._conn.execute(f"INSTALL {extension_name}")
            self._conn.execute(f"LOAD {extension_name}")

        if self.config.secrets:
            for secret in self.config.secrets:
                self._create_secret(secret)

        if self.config.attach:
            for attach_spec in self.config.attach:
                self._attach_database(attach_spec)

    def _create_secret(self, secret: SecretSpec) -> None:
        params_sql = ",\n    ".join(
            f"{param_name} {_quote_string_literal(param_value)}"
            for param_name, param_value in secret.parameters.items()
        )
        sql = (
            f"CREATE OR REPLACE SECRET {_quote_ident(secret.name)} (\n"
            f"    TYPE {secret.type},\n"
            f"    {params_sql}\n"
            f")"
        )
        self._conn.execute(sql)

    def _attach_database(self, attach_spec: AttachSpec) -> None:
        options: list[str] = []
        if attach_spec.read_only:
            options.append("READ_ONLY")
        if attach_spec.type:
            options.append(f"TYPE {attach_spec.type}")
        options_clause = f" ({', '.join(options)})" if options else ""
        sql = (
            f"ATTACH {_quote_string_literal(attach_spec.target)}"
            f" AS {_quote_ident(attach_spec.alias)}"
            f"{options_clause}"
        )
        self._conn.execute(sql)

    def _describe_source_columns(self) -> list[tuple[str, str]]:
        """Return ``[(column_name, duckdb_type_str), …]`` for the configured source."""
        sql = f"DESCRIBE SELECT * FROM ({self.config.source}) AS _src LIMIT 0"
        cursor = self._conn.cursor()
        cursor.execute(sql)
        # DESCRIBE result columns: column_name, column_type, null, key, default, extra
        return [
            (description_entry[0], description_entry[1])
            for description_entry in cursor.fetchall()
        ]

    def _validate_columns(self) -> None:
        column_names = {name for name, _ in self._columns}
        missing = [
            label
            for column, label in (
                (
                    self.config.geometry_column,
                    f"geometry column {self.config.geometry_column!r}",
                ),
                (self.config.id_column, f"id column {self.config.id_column!r}"),
            )
            if column not in column_names
        ]
        if missing:
            raise ValueError(
                f"Source {self.config.source!r} is missing: {', '.join(missing)}. "
                f"Available columns: {sorted(column_names)}"
            )

    def _get_column_type(self, column_name: str) -> str:
        for name, type_str in self._columns:
            if name == column_name:
                return type_str
        raise KeyError(f"Unknown column: {column_name!r}")

    async def _execute(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        def _run() -> list[dict[str, Any]]:
            cursor = self._conn.cursor()
            cursor.execute(sql, list(params))
            column_names = [
                description_entry[0] for description_entry in cursor.description
            ]
            return [dict(zip(column_names, row)) for row in cursor.fetchall()]

        return await asyncio.to_thread(_run)

    async def _execute_scalar(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        def _run() -> Any:
            cursor = self._conn.cursor()
            cursor.execute(sql, list(params))
            row = cursor.fetchone()
            return row[0] if row else None

        return await asyncio.to_thread(_run)

    async def _get_native_srid(self) -> int:
        """Return the integer SRID of the configured source.

        DuckDB's geometry type does not embed per-geometry SRID (unlike PostGIS),
        so the native CRS must come from operator-supplied config.  When
        ``storage_crs`` is not set we default to 4326 (WGS 84), which covers the
        overwhelming majority of geospatial datasets.  For projected or non-WGS 84
        sources, set ``storage_crs`` explicitly in the collection config.
        """
        if self._cached_native_srid is not None:
            return self._cached_native_srid

        if self.config.storage_crs:
            srid = _parse_srid_from_crs_uri(self.config.storage_crs)
        else:
            srid = 4326

        self._cached_native_srid = srid
        return srid

    def _build_predicates(
        self,
        feature_filter: PottoFeatureFilter,
        native_srid: int,
    ) -> tuple[list[str], list[Any]]:
        """Return ``(where_clauses, positional_params)`` for the given filter."""
        where_clauses: list[str] = []
        params: list[Any] = []

        if feature_filter.bbox is not None:
            bbox_srid = _parse_srid_from_crs_uri(feature_filter.bbox_crs)
            quoted_geom_col = _quote_ident(self.config.geometry_column)
            # DuckDB spatial: ST_MakeEnvelope(xmin, ymin, xmax, ymax) — no SRID arg.
            # ST_Transform takes explicit string CRS identifiers ('EPSG:N'), not
            # integer SRIDs.  No ST_SetSRID/ST_SetCRS call needed because the source
            # CRS is passed explicitly to ST_Transform.
            if bbox_srid == native_srid:
                envelope_expr = "ST_MakeEnvelope(?, ?, ?, ?)"
            else:
                source_crs = _quote_string_literal(
                    _format_srid_as_epsg_string(bbox_srid)
                )
                target_crs = _quote_string_literal(
                    _format_srid_as_epsg_string(native_srid)
                )
                envelope_expr = f"ST_Transform(ST_MakeEnvelope(?, ?, ?, ?), {source_crs}, {target_crs})"
            where_clauses.append(f"ST_Intersects({quoted_geom_col}, {envelope_expr})")
            params.extend(feature_filter.bbox)

        return where_clauses, params

    def _build_features_query(
        self,
        target_srid: int,
        native_srid: int,
        feature_filter: PottoFeatureFilter | None = None,
        with_paging: bool = True,
        where_id: bool = False,
    ) -> tuple[str, tuple[Any, ...]]:
        geometry_column = self.config.geometry_column
        quoted_geom_col = _quote_ident(geometry_column)

        non_geometry_columns = [
            _quote_ident(name) for name, _ in self._columns if name != geometry_column
        ]

        if target_srid == native_srid:
            geom_expr = f"ST_AsGeoJSON({quoted_geom_col})"
        else:
            source_crs = _quote_string_literal(_format_srid_as_epsg_string(native_srid))
            target_crs = _quote_string_literal(_format_srid_as_epsg_string(target_srid))
            geom_expr = f"ST_AsGeoJSON(ST_Transform({quoted_geom_col}, {source_crs}, {target_crs}))"

        select_expressions = non_geometry_columns + [
            f"{geom_expr} AS {quoted_geom_col}"
        ]
        sql = (
            f"SELECT {', '.join(select_expressions)}\n"
            f"FROM ({self.config.source}) AS _src"
        )

        params: list[Any] = []
        where_clauses: list[str] = []

        if feature_filter is not None:
            predicate_clauses, predicate_params = self._build_predicates(
                feature_filter, native_srid
            )
            where_clauses.extend(predicate_clauses)
            params.extend(predicate_params)

        if where_id:
            quoted_id_col = _quote_ident(self.config.id_column)
            where_clauses.append(f"{quoted_id_col} = ?")
            # Caller appends the id value as the last positional parameter.

        if where_clauses:
            sql += "\nWHERE " + " AND ".join(where_clauses)

        if with_paging and feature_filter is not None:
            sql += "\nLIMIT ? OFFSET ?"
            params.extend([feature_filter.limit, feature_filter.offset])

        return sql, tuple(params)

    def _build_count_query(
        self,
        native_srid: int,
        feature_filter: PottoFeatureFilter,
    ) -> tuple[str, tuple[Any, ...]]:
        where_clauses, params = self._build_predicates(feature_filter, native_srid)
        sql = f"SELECT COUNT(*)\nFROM ({self.config.source}) AS _src"
        if where_clauses:
            sql += "\nWHERE " + " AND ".join(where_clauses)
        return sql, tuple(params)

    def _coerce_id(self, raw: str) -> Any:
        """Coerce the string feature_id from the request to the id column's native type."""
        id_type = self._get_column_type(self.config.id_column).upper()
        if id_type in _INTEGER_TYPES:
            try:
                return int(raw)
            except ValueError as exc:
                raise ValueError(
                    f"feature_id {raw!r} cannot be coerced to integer "
                    f"(id column type is {id_type!r})"
                ) from exc
        # UUID, VARCHAR, and most other types accept the string directly.
        return raw

    def _convert_row_to_feature(
        self,
        row: dict[str, Any],
        *,
        projection: list[str] | None = None,
    ) -> Feature:
        geom_str: str | None = row.pop(self.config.geometry_column, None)
        feature_id = row.pop(self.config.id_column, None)

        # ST_AsGeoJSON returns a JSON string; parse it into a shapely geometry.
        geometry = shapely.from_geojson(geom_str) if geom_str else None

        if projection is not None:
            row = {key: value for key, value in row.items() if key in projection}

        return Feature(
            id_=str(feature_id) if feature_id is not None else "",
            geometry=geometry,  # type: ignore[arg-type]  # Feature.geometry is non-optional in type stub
            properties=row,
        )

    async def _detect_geometry_type(self) -> str | None:
        """Return a single geometry type string when all features share one type.

        Returns ``None`` when the source contains mixed geometry types (or is empty).
        Result is not cached because it is only called from ``get_schema``, which is
        itself expected to be cached at the caller level.
        """
        quoted_geom_col = _quote_ident(self.config.geometry_column)
        sql = (
            f"SELECT DISTINCT ST_GeometryType({quoted_geom_col}) AS geom_type\n"
            f"FROM ({self.config.source}) AS _src\n"
            f"WHERE {quoted_geom_col} IS NOT NULL\n"
            f"LIMIT 2"
        )
        rows = await self._execute(sql)
        if len(rows) == 1:
            return rows[0].get("geom_type")
        return None

    def _build_geometry_column_schema(
        self, geom_type: str | None, native_srid: int
    ) -> dict[str, Any]:
        geometry_format = (
            _GEOMETRY_TYPE_TO_FORMAT.get(geom_type.upper(), "geometry-any")
            if geom_type
            else "geometry-any"
        )
        schema: dict[str, Any] = {
            "format": geometry_format,
            "x-ogc-role": "primary-geometry",
        }
        if native_srid and native_srid != 4326:
            schema["x-ogc-srs"] = _format_srid_as_crs_uri(native_srid)
        return schema

    async def list_features(
        self, feature_filter: PottoFeatureFilter | None = None
    ) -> list[Feature]:
        effective_filter = feature_filter or PottoFeatureFilter()
        target_srid = _parse_srid_from_crs_uri(effective_filter.crs)
        native_srid = await self._get_native_srid()

        sql, params = self._build_features_query(
            target_srid=target_srid,
            native_srid=native_srid,
            feature_filter=effective_filter,
            with_paging=True,
        )
        rows = await self._execute(sql, params)
        return [
            self._convert_row_to_feature(row, projection=effective_filter.properties)
            for row in rows
        ]

    async def count_items(
        self, feature_filter: PottoFeatureFilter | None = None
    ) -> CountedItems:
        effective_filter = feature_filter or PottoFeatureFilter()
        native_srid = await self._get_native_srid()

        count_sql, params = self._build_count_query(
            native_srid=native_srid, feature_filter=effective_filter
        )
        matched: int = (await self._execute_scalar(count_sql, params)) or 0

        remaining = max(matched - effective_filter.offset, 0)
        returned = min(effective_filter.limit, remaining)
        return CountedItems(matched=matched, total=returned)

    async def get_feature(self, feature_id: str, crs: str = CRS_84) -> Feature | None:
        target_srid = _parse_srid_from_crs_uri(crs)
        native_srid = await self._get_native_srid()
        coerced_id = self._coerce_id(feature_id)

        sql, params = self._build_features_query(
            target_srid=target_srid,
            native_srid=native_srid,
            with_paging=False,
            where_id=True,
        )
        rows = await self._execute(sql, (*params, coerced_id))
        return self._convert_row_to_feature(rows[0]) if rows else None

    async def get_schema(self) -> JsonSchemaValue:
        native_srid = await self._get_native_srid()
        geom_type = await self._detect_geometry_type()

        properties: dict[str, Any] = {}
        for col_name, col_type in self._columns:
            if col_name == self.config.geometry_column:
                properties[col_name] = self._build_geometry_column_schema(
                    geom_type, native_srid
                )
            elif col_name == self.config.id_column:
                properties[col_name] = {
                    **_map_duckdb_type_to_json_schema(col_type),
                    "x-ogc-role": "id",
                }
            else:
                properties[col_name] = _map_duckdb_type_to_json_schema(col_type)

        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "title": self.config.source,
            "properties": properties,
        }

    async def get_queryables(self) -> JsonSchemaValue:
        """Return queryable (non-geometry) column schemas.

        The geometry column is excluded; all other columns including the id
        column are listed because they are valid filter targets.
        """
        properties: dict[str, Any] = {
            col_name: _map_duckdb_type_to_json_schema(col_type)
            for col_name, col_type in self._columns
            if col_name != self.config.geometry_column
        }
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "title": "Queryables",
            "properties": properties,
        }

    async def get_storage_crs(self) -> StorageCrs | None:
        if self._cached_storage_crs is not None:
            return self._cached_storage_crs

        if self.config.storage_crs:
            storage_crs = StorageCrs(crs=self.config.storage_crs)
        else:
            native_srid = await self._get_native_srid()
            storage_crs = (
                StorageCrs(crs=_format_srid_as_crs_uri(native_srid))
                if native_srid
                else None
            )

        self._cached_storage_crs = storage_crs
        return storage_crs

    async def get_spatial_extent(
        self,
    ) -> TwoDimensionalSpatialExtent | ThreeDimensionSpatialExtent | None:
        if self._cached_spatial_extent is not None:
            return self._cached_spatial_extent

        native_srid = await self._get_native_srid()
        quoted_geom_col = _quote_ident(self.config.geometry_column)

        # Always return extent in CRS84 per OGC convention.
        # ST_Transform takes string CRS identifiers in DuckDB spatial.
        # ST_Extent_Agg returns GEOMETRY (not a BOX_2D struct), so we use
        # ST_XMin / ST_YMin / ST_XMax / ST_YMax to extract the coordinates.
        if native_srid == 4326:
            geom_expr = quoted_geom_col
        else:
            source_crs = _quote_string_literal(_format_srid_as_epsg_string(native_srid))
            geom_expr = f"ST_Transform({quoted_geom_col}, {source_crs}, 'EPSG:4326')"

        sql = (
            f"WITH bbox AS (\n"
            f"    SELECT ST_Extent_Agg({geom_expr}) AS extent\n"
            f"    FROM ({self.config.source}) AS _src\n"
            f")\n"
            f"SELECT\n"
            f"    ST_XMin(extent) AS xmin,\n"
            f"    ST_YMin(extent) AS ymin,\n"
            f"    ST_XMax(extent) AS xmax,\n"
            f"    ST_YMax(extent) AS ymax\n"
            f"FROM bbox"
        )
        rows = await self._execute(sql)
        if not rows or rows[0].get("xmin") is None:
            return None

        bounds_row = rows[0]
        extent: TwoDimensionalSpatialExtent = TwoDimensionalSpatialExtent(
            bbox=[
                (
                    bounds_row["xmin"],
                    bounds_row["ymin"],
                    bounds_row["xmax"],
                    bounds_row["ymax"],
                )
            ]
        )
        self._cached_spatial_extent = extent
        return extent

    async def get_temporal_extent(self) -> TemporalExtent | None:
        if self._cached_temporal_extent is not None:
            return self._cached_temporal_extent

        if self.config.temporal_column is not None:
            quoted_temporal_col = _quote_ident(self.config.temporal_column)
            sql = (
                f'SELECT MIN({quoted_temporal_col}) AS "temporal_begin",\n'
                f'       MAX({quoted_temporal_col}) AS "temporal_end"\n'
                f"FROM ({self.config.source}) AS _src"
            )
            rows = await self._execute(sql)
            if rows:
                begin_str = _format_as_iso_string(rows[0].get("temporal_begin"))
                end_str = _format_as_iso_string(rows[0].get("temporal_end"))
                if begin_str or end_str:
                    extent = TemporalExtent(interval=[(begin_str, end_str)])
                    self._cached_temporal_extent = extent
                    return extent

        elif self.config.temporal_interval_columns is not None:
            start_col, end_col = self.config.temporal_interval_columns
            quoted_start_col = _quote_ident(start_col)
            quoted_end_col = _quote_ident(end_col)
            sql = (
                f'SELECT MIN({quoted_start_col}) AS "temporal_begin",\n'
                f'       MAX({quoted_end_col}) AS "temporal_end"\n'
                f"FROM ({self.config.source}) AS _src"
            )
            rows = await self._execute(sql)
            if rows:
                begin_str = _format_as_iso_string(rows[0].get("temporal_begin"))
                end_str = _format_as_iso_string(rows[0].get("temporal_end"))
                if begin_str or end_str:
                    extent = TemporalExtent(interval=[(begin_str, end_str)])
                    self._cached_temporal_extent = extent
                    return extent

        return None

    async def get_additional_extents(self) -> list[AdditionalExtent] | None:
        return None


async def duckdb_provider_factory(
    collection: "Collection",  # noqa: ARG001 — required by factory protocol; not used
    raw_config: dict[str, Any],
    session: "AsyncSession",  # noqa: ARG001 — DuckDB does not use the SQLAlchemy session
    potto_config: "PottoSettings",
) -> DuckdbFeatureProvider:
    # TODO: provider caching — see module docstring.
    config = DuckdbFeatureProviderConfiguration.model_validate(raw_config)
    # Run DuckDB setup in a thread so extension loading and schema probing
    # (which are synchronous) do not block the async event loop.
    return await asyncio.to_thread(DuckdbFeatureProvider, config, potto_config)
