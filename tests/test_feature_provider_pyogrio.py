import math
import datetime

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import pytest
from shapely.geometry import Point

from potto.config import PottoSettings
from potto.providers.features import _pyogrio
from potto.schemas.base import PottoFeatureFilter


@pytest.fixture
def geojson_uri():
    gdf = gpd.GeoDataFrame(
        {
            "name": ["alpha", "beta", "gamma"],
            "value": [1, 2, 3],
            "geometry": [Point(10, 20), Point(30, 40), Point(50, 60)],
        },
        crs="EPSG:4326",
    )
    uri = "/vsimem/test_features.geojson"
    pyogrio.write_dataframe(gdf, uri, driver="GeoJSON")
    yield uri
    pyogrio.vsi_unlink(uri)


@pytest.fixture
def geojson_uri_with_id_column():
    gdf = gpd.GeoDataFrame(
        {
            "fid": ["feat-1", "feat-2"],
            "name": ["alpha", "beta"],
            "geometry": [Point(10, 20), Point(30, 40)],
        },
        crs="EPSG:4326",
    )
    uri = "/vsimem/test_features_with_id.geojson"
    pyogrio.write_dataframe(gdf, uri, driver="GeoJSON")
    yield uri
    pyogrio.vsi_unlink(uri)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (float("nan"), None),
        (np.float64(math.nan), None),
        (np.int64(42), 42),
        (np.int32(-7), -7),
        (np.uint8(255), 255),
        (np.float64(3.14), 3.14),
        (np.bool_(True), True),
        (np.bool_(False), False),
        ("hello", "hello"),
        (99, 99),
        pytest.param(
            pd.Timestamp("2024-06-15T12:00:00Z"),
            datetime.datetime(2024, 6, 15, 12, 0, tzinfo=datetime.timezone.utc),
            id="timestamp_to_datetime",
        ),
    ],
)
def test_coerce_value(value, expected):
    result = _pyogrio._coerce_value(value)
    assert (
        result == pytest.approx(expected)
        if isinstance(expected, float)
        else result == expected
    )
    assert type(result) is type(expected)


@pytest.mark.parametrize(
    "dtype,expected_schema",
    [
        ("int64", {"type": "integer"}),
        ("float64", {"type": "number"}),
        ("bool", {"type": "boolean"}),
        ("object", {"type": "string"}),
        ("datetime64[ns]", {"type": "string", "format": "date-time"}),
        ("datetime64[us, UTC]", {"type": "string", "format": "date-time"}),
        ("date32", {"type": "string", "format": "date"}),
        ("date", {"type": "string", "format": "date"}),
        pytest.param(
            "unknown_type", {"type": "string"}, id="unknown_falls_back_to_string"
        ),
    ],
)
def test_map_dtype_to_json_schema(dtype, expected_schema):
    assert _pyogrio._map_dtype_to_json_schema(dtype) == expected_schema


@pytest.mark.parametrize(
    "geometry_type,expected_format",
    [
        ("Point", "geometry-point"),
        ("MultiPoint", "geometry-multipoint"),
        ("LineString", "geometry-linestring"),
        ("MultiLineString", "geometry-multilinestring"),
        ("Polygon", "geometry-polygon"),
        ("MultiPolygon", "geometry-multipolygon"),
        ("GeometryCollection", "geometry-geometrycollection"),
        pytest.param("Point Z", "geometry-point", id="Point_Z_3D_variant"),
        pytest.param("Polygon ZM", "geometry-polygon", id="Polygon_ZM_variant"),
        pytest.param("Unknown", "geometry-any", id="Unknown_falls_back_to_any"),
        pytest.param(None, "geometry-any", id="None_falls_back_to_any"),
    ],
)
def test_map_geometry_type_to_json_schema(geometry_type, expected_format):
    result = _pyogrio._map_geometry_type_to_json_schema(geometry_type)
    assert result["format"] == expected_format
    assert result["x-ogc-role"] == "primary-geometry"


@pytest.mark.parametrize(
    "authority,expected_uri",
    [
        (("EPSG", "4326"), "http://www.opengis.net/def/crs/EPSG/0/4326"),
        (("EPSG", "3857"), "http://www.opengis.net/def/crs/EPSG/0/3857"),
        (("OGC", "CRS84"), "http://www.opengis.net/def/crs/OGC/1.3/CRS84"),
        pytest.param(None, None, id="no_authority"),
    ],
)
def test_format_crs_as_uri(authority, expected_uri):
    assert _pyogrio._format_crs_as_uri(authority) == expected_uri


def test_build_where_clause_returns_none_for_empty_filter():
    # Must return None, not "", because pyogrio treats an empty string as an invalid WHERE clause
    assert _pyogrio._build_where_clause(PottoFeatureFilter(limit=10, offset=0)) is None


def test_build_feature_from_series_geometry_excluded_from_properties():
    row = pd.Series({"name": "alpha", "geometry": Point(10, 20)})
    feature = _pyogrio._build_feature_from_series(row, geom_col="geometry", id_value=0)
    assert "geometry" not in feature.properties


def test_build_feature_from_series_id_column_excluded_from_properties():
    row = pd.Series({"fid": "feat-1", "name": "alpha", "geometry": Point(10, 20)})
    feature = _pyogrio._build_feature_from_series(
        row, geom_col="geometry", id_value="feat-1", id_column="fid"
    )
    assert "fid" not in feature.properties


def test_build_features_from_geodataframe_uses_index_as_id_by_default():
    gdf = gpd.GeoDataFrame(
        {"name": ["a"], "geometry": [Point(1, 2)]},
        crs="EPSG:4326",
    )
    features = _pyogrio._build_features_from_geodataframe(gdf)
    assert features[0].id_ == str(gdf.index[0])


def test_build_features_from_geodataframe_uses_named_column_as_id():
    gdf = gpd.GeoDataFrame(
        {"fid": ["feat-1"], "name": ["a"], "geometry": [Point(1, 2)]},
        crs="EPSG:4326",
    )
    features = _pyogrio._build_features_from_geodataframe(gdf, id_column="fid")
    assert features[0].id_ == "feat-1"


@pytest.mark.parametrize(
    "limit,offset,expected_count",
    [
        pytest.param(10, 0, 3, id="all_features"),
        pytest.param(2, 0, 2, id="first_two"),
        pytest.param(10, 1, 2, id="skip_one"),
        pytest.param(10, 3, 0, id="skip_all"),
    ],
)
def test_list_features_pagination(geojson_uri, limit, offset, expected_count):
    feature_filter = PottoFeatureFilter(limit=limit, offset=offset)
    assert len(_pyogrio._list_features(geojson_uri, feature_filter)) == expected_count


def test_list_features_bbox_excludes_out_of_range_points(geojson_uri):
    # Points at [10,20], [30,40], [50,60] — bbox covers only the first two
    feature_filter = PottoFeatureFilter(
        limit=10, offset=0, bbox=(5.0, 15.0, 35.0, 45.0)
    )
    assert len(_pyogrio._list_features(geojson_uri, feature_filter)) == 2


def test_list_features_id_column_used_as_id(geojson_uri_with_id_column):
    feature_filter = PottoFeatureFilter(limit=10, offset=0)
    features = _pyogrio._list_features(
        geojson_uri_with_id_column, feature_filter, id_column="fid"
    )
    assert {feature.id_ for feature in features} == {"feat-1", "feat-2"}


def test_list_features_id_column_absent_from_properties(geojson_uri_with_id_column):
    feature_filter = PottoFeatureFilter(limit=10, offset=0)
    features = _pyogrio._list_features(
        geojson_uri_with_id_column, feature_filter, id_column="fid"
    )
    for feature in features:
        assert "fid" not in feature.properties


@pytest.mark.parametrize(
    "feature_filter,expected_total,expected_matched",
    [
        pytest.param(None, 3, 3, id="no_filter"),
        pytest.param(
            PottoFeatureFilter(limit=10, offset=0, bbox=(5.0, 15.0, 35.0, 45.0)),
            3,
            2,
            id="bbox_filter",
        ),
    ],
)
def test_count_features(geojson_uri, feature_filter, expected_total, expected_matched):
    counts = _pyogrio._count_features(geojson_uri, feature_filter)
    assert counts.total == expected_total
    assert counts.matched == expected_matched


def test_get_schema_has_exactly_one_primary_geometry_field(geojson_uri):
    properties = _pyogrio._get_schema(geojson_uri)["properties"]
    primary_geometry_fields = [
        field_name
        for field_name, field_schema in properties.items()
        if field_schema.get("x-ogc-role") == "primary-geometry"
    ]
    assert len(primary_geometry_fields) == 1


def test_get_schema_id_column_receives_ogc_id_role(geojson_uri_with_id_column):
    properties = _pyogrio._get_schema(geojson_uri_with_id_column, id_column="fid")[
        "properties"
    ]
    assert properties["fid"]["x-ogc-role"] == "id"


def test_get_feature_by_fid_returns_correct_feature(geojson_uri):
    all_features = _pyogrio._list_features(
        geojson_uri, PottoFeatureFilter(limit=10, offset=0)
    )
    target = all_features[0]
    result = _pyogrio._get_feature(geojson_uri, target.id_)
    assert result is not None
    assert result.id_ == target.id_
    assert result.properties["name"] == target.properties["name"]


@pytest.mark.parametrize(
    "feature_id",
    [
        pytest.param("9999", id="nonexistent_fid"),
        pytest.param("not-a-number", id="non_integer_fid"),
    ],
)
def test_get_feature_by_fid_returns_none_when_not_found(geojson_uri, feature_id):
    assert _pyogrio._get_feature(geojson_uri, feature_id) is None


def test_get_feature_by_id_column_returns_correct_feature(geojson_uri_with_id_column):
    result = _pyogrio._get_feature(
        geojson_uri_with_id_column, "feat-1", id_column="fid"
    )
    assert result is not None
    assert result.id_ == "feat-1"
    assert result.properties["name"] == "alpha"


@pytest.mark.parametrize(
    "feature_id",
    [
        "nonexistent",
        pytest.param("' OR '1'='1", id="sql_injection_attempt"),
    ],
)
def test_get_feature_by_id_column_returns_none_when_not_found(
    geojson_uri_with_id_column, feature_id
):
    assert (
        _pyogrio._get_feature(geojson_uri_with_id_column, feature_id, id_column="fid")
        is None
    )


def test_list_features_reprojects_to_requested_crs(geojson_uri):
    # Point(10, 20) in EPSG:4326 → approx (1113194.9, 2273030.9) in EPSG:3857
    feature_filter = PottoFeatureFilter(
        limit=10,
        offset=0,
        crs="http://www.opengis.net/def/crs/EPSG/0/3857",
    )
    features = _pyogrio._list_features(geojson_uri, feature_filter)
    first_geom = features[0].geometry
    assert first_geom.x == pytest.approx(1113194.9, rel=1e-4)
    assert first_geom.y == pytest.approx(2273030.9, rel=1e-4)


def test_get_feature_reprojects_to_requested_crs(geojson_uri):
    all_features = _pyogrio._list_features(
        geojson_uri, PottoFeatureFilter(limit=10, offset=0)
    )
    target = all_features[0]
    feature = _pyogrio._get_feature(
        geojson_uri,
        target.id_,
        crs="http://www.opengis.net/def/crs/EPSG/0/3857",
    )
    assert feature is not None
    # Point(10, 20) in EPSG:4326 → approx (1113194.9, 2273030.9) in EPSG:3857
    assert feature.geometry.x == pytest.approx(1113194.9, rel=1e-4)
    assert feature.geometry.y == pytest.approx(2273030.9, rel=1e-4)


def test_get_storage_crs_returns_well_formed_uri_for_geojson(geojson_uri):
    storage_crs = _pyogrio._get_storage_crs(geojson_uri)
    assert storage_crs is not None
    assert storage_crs.crs.startswith("http://www.opengis.net/def/crs/")


def test_csv_gdal_options_bools_map_to_yes_no():
    kwargs = _pyogrio.PyogrioCsvGdalOpenOption(
        autodetect_type=False, keep_source_columns=True, keep_geom_columns=True
    ).as_read_dataframe_kwargs()
    assert kwargs["AUTODETECT_TYPE"] == "NO"
    assert kwargs["KEEP_SOURCE_COLUMNS"] == "YES"
    assert kwargs["KEEP_GEOM_COLUMNS"] == "YES"


def test_csv_gdal_options_multiple_names_joined_by_comma():
    kwargs = _pyogrio.PyogrioCsvGdalOpenOption(
        x_possible_names=["lon", "longitude", "x"]
    ).as_read_dataframe_kwargs()
    assert kwargs["X_POSSIBLE_NAMES"] == "lon,longitude,x"


def test_csv_gdal_options_none_list_excluded_from_kwargs():
    kwargs = _pyogrio.PyogrioCsvGdalOpenOption(
        x_possible_names=None, geom_possible_names=None
    ).as_read_dataframe_kwargs()
    assert "X_POSSIBLE_NAMES" not in kwargs
    assert "GEOM_POSSIBLE_NAMES" not in kwargs


def test_geojson_gdal_options_bool_maps_to_no():
    kwargs = _pyogrio.PyogrioGeoJsonGdalOpenOption(
        flatten_nested_attributes=False
    ).as_read_dataframe_kwargs()
    assert kwargs["FLATTEN_NESTED_ATTRIBUTES"] == "NO"


def test_provider_factory_returns_configured_provider():
    provider = _pyogrio.pyogrio_provider_factory(
        collection=None,
        raw_config={"data_source_uri": "/path/to/data.geojson"},
        session=None,
        potto_config=PottoSettings(),
    )
    assert isinstance(provider, _pyogrio.PyogrioFeatureProvider)
    assert provider.config.data_source_uri == "/path/to/data.geojson"


@pytest.mark.asyncio
async def test_provider_list_features_uses_page_size_when_no_filter_given(geojson_uri):
    config = _pyogrio.PyogrioFeatureProviderConfiguration(data_source_uri=geojson_uri)
    features = await _pyogrio.PyogrioFeatureProvider(
        config, PottoSettings(page_size=2)
    ).list_features()
    assert len(features) == 2
