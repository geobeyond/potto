import pytest

from potto.config import PottoSettings
from potto.constants import CRS_84
from potto.providers.features import _duckdb
from potto.schemas.features import PottoFeatureFilter

_EPSG3857 = "http://www.opengis.net/def/crs/EPSG/0/3857"

_SOURCE = (
    "SELECT 1 AS fid, ST_GeomFromText('POINT (10 20)') AS geom, 'alpha' AS name "
    "UNION ALL "
    "SELECT 2 AS fid, ST_GeomFromText('POINT (30 40)') AS geom, 'beta' AS name "
    "UNION ALL "
    "SELECT 3 AS fid, ST_GeomFromText('POINT (50 60)') AS geom, 'gamma' AS name"
)


@pytest.fixture
def provider():
    config = _duckdb.DuckdbFeatureProviderConfiguration(
        source=_SOURCE,
        geometry_column="geom",
        id_column="fid",
    )
    return _duckdb.DuckdbFeatureProvider(config, PottoSettings())


# ── pure function tests ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "uri,expected_srid",
    [
        ("http://www.opengis.net/def/crs/OGC/1.3/CRS84", 4326),
        ("http://www.opengis.net/def/crs/OGC/0/CRS84h", 4326),
        ("http://www.opengis.net/def/crs/EPSG/0/4326", 4326),
        ("http://www.opengis.net/def/crs/EPSG/0/3857", 3857),
    ],
)
def test_parse_srid_from_crs_uri(uri, expected_srid):
    assert _duckdb._parse_srid_from_crs_uri(uri) == expected_srid


def test_parse_srid_from_crs_uri_raises_for_unsupported():
    with pytest.raises(ValueError, match="Unsupported CRS URI"):
        _duckdb._parse_srid_from_crs_uri(
            "http://www.opengis.net/def/crs/EPSG/0/not-a-number"
        )


@pytest.mark.parametrize(
    "srid,expected_uri",
    [
        (4326, CRS_84),
        (3857, "http://www.opengis.net/def/crs/EPSG/0/3857"),
        (25832, "http://www.opengis.net/def/crs/EPSG/0/25832"),
    ],
)
def test_format_srid_as_crs_uri(srid, expected_uri):
    assert _duckdb._format_srid_as_crs_uri(srid) == expected_uri


@pytest.mark.parametrize(
    "type_str,expected",
    [
        ("INTEGER", {"type": "integer"}),
        ("BIGINT", {"type": "integer"}),
        ("DOUBLE", {"type": "number"}),
        ("FLOAT", {"type": "number"}),
        ("VARCHAR", {"type": "string"}),
        ("BOOLEAN", {"type": "boolean"}),
        ("DATE", {"type": "string", "format": "date"}),
        ("TIMESTAMP", {"type": "string", "format": "date-time"}),
        ("UUID", {"type": "string", "format": "uuid"}),
        pytest.param("unknown_type", {}, id="unknown_falls_back_to_empty"),
    ],
)
def test_map_duckdb_type_to_json_schema(type_str, expected):
    assert _duckdb._map_duckdb_type_to_json_schema(type_str) == expected


def test_quote_ident_wraps_in_double_quotes():
    assert _duckdb._quote_ident("my_col") == '"my_col"'


def test_quote_ident_escapes_embedded_double_quotes():
    assert _duckdb._quote_ident('weird"name') == '"weird""name"'


def test_quote_string_literal_wraps_in_single_quotes():
    assert _duckdb._quote_string_literal("hello") == "'hello'"


def test_quote_string_literal_escapes_embedded_single_quotes():
    assert _duckdb._quote_string_literal("it's") == "'it''s'"


# ── integration tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "limit,offset,expected_count",
    [
        pytest.param(10, 0, 3, id="all_features"),
        pytest.param(2, 0, 2, id="first_two"),
        pytest.param(10, 1, 2, id="skip_one"),
        pytest.param(10, 3, 0, id="skip_all"),
    ],
)
async def test_list_features_pagination(provider, limit, offset, expected_count):
    feature_filter = PottoFeatureFilter(limit=limit, offset=offset)
    features = await provider.list_features(feature_filter)
    assert len(features) == expected_count


@pytest.mark.asyncio
async def test_list_features_bbox_excludes_out_of_range_points(provider):
    # Points at [10,20], [30,40], [50,60] — bbox covers only the first two
    feature_filter = PottoFeatureFilter(
        limit=10, offset=0, bbox=(5.0, 15.0, 35.0, 45.0)
    )
    features = await provider.list_features(feature_filter)
    assert len(features) == 2


@pytest.mark.asyncio
async def test_count_items_returns_matched_count(provider):
    result = await provider.count_items()
    assert result.matched == 3


@pytest.mark.asyncio
async def test_count_items_bbox_affects_matched_count(provider):
    feature_filter = PottoFeatureFilter(
        limit=10, offset=0, bbox=(5.0, 15.0, 35.0, 45.0)
    )
    result = await provider.count_items(feature_filter)
    assert result.matched == 2


@pytest.mark.asyncio
async def test_get_feature_returns_correct_feature(provider):
    result = await provider.get_feature("1")
    assert result is not None
    assert result.id_ == "1"
    assert result.properties["name"] == "alpha"


@pytest.mark.asyncio
async def test_get_feature_returns_none_for_nonexistent_id(provider):
    assert await provider.get_feature("9999") is None


@pytest.mark.asyncio
async def test_get_feature_raises_for_non_integer_id_on_integer_column(provider):
    with pytest.raises(ValueError):
        await provider.get_feature("not-a-number")


@pytest.mark.asyncio
async def test_get_schema_has_exactly_one_primary_geometry_field(provider):
    schema = await provider.get_schema()
    primary_geometry_fields = [
        name
        for name, field_schema in schema["properties"].items()
        if field_schema.get("x-ogc-role") == "primary-geometry"
    ]
    assert len(primary_geometry_fields) == 1


@pytest.mark.asyncio
async def test_get_schema_id_column_receives_ogc_id_role(provider):
    schema = await provider.get_schema()
    assert schema["properties"]["fid"]["x-ogc-role"] == "id"


@pytest.mark.asyncio
async def test_get_storage_crs_defaults_to_crs84(provider):
    result = await provider.get_storage_crs()
    assert result is not None
    assert result.crs == CRS_84


@pytest.mark.asyncio
async def test_get_storage_crs_returns_configured_crs():
    config = _duckdb.DuckdbFeatureProviderConfiguration(
        source="SELECT 1 AS fid, ST_GeomFromText('POINT (0 0)') AS geom",
        geometry_column="geom",
        id_column="fid",
        storage_crs=_EPSG3857,
    )
    provider = _duckdb.DuckdbFeatureProvider(config, PottoSettings())
    result = await provider.get_storage_crs()
    assert result is not None
    assert result.crs == _EPSG3857


@pytest.mark.asyncio
async def test_list_features_reprojects_to_requested_crs(provider):
    # Point(10, 20) in EPSG:4326 → approx (1113194.9, 2273030.9) in EPSG:3857
    feature_filter = PottoFeatureFilter(limit=10, offset=0, crs=_EPSG3857)
    features = await provider.list_features(feature_filter)
    first_geom = features[0].geometry
    assert first_geom.x == pytest.approx(1113194.9, rel=1e-4)
    assert first_geom.y == pytest.approx(2273030.9, rel=1e-4)


@pytest.mark.asyncio
async def test_get_feature_reprojects_to_requested_crs(provider):
    # Point(10, 20) in EPSG:4326 → approx (1113194.9, 2273030.9) in EPSG:3857
    feature = await provider.get_feature("1", crs=_EPSG3857)
    assert feature is not None
    assert feature.geometry.x == pytest.approx(1113194.9, rel=1e-4)
    assert feature.geometry.y == pytest.approx(2273030.9, rel=1e-4)
