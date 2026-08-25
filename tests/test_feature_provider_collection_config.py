import pydantic
import pytest

from potto.config import PottoSettings
from potto.constants import CRS_84
from potto.providers.features import _collectionconfig
from potto.providers.features.protocol import FeatureProviderProtocol
from potto.schemas.base import PottoFeatureFilter

_EPSG3857 = "http://www.opengis.net/def/crs/EPSG/0/3857"

_RAW_FEATURES = [
    _collectionconfig.WktFeatureItem(
        id_="1", properties={"name": "alpha", "value": 1}, geometry="POINT (10 20)"
    ),
    _collectionconfig.WktFeatureItem(
        id_="2", properties={"name": "beta", "value": 2}, geometry="POINT (30 40)"
    ),
    _collectionconfig.WktFeatureItem(
        id_="3", properties={"name": "gamma", "value": 3}, geometry="POINT (50 60)"
    ),
]


@pytest.fixture
def provider():
    config = _collectionconfig.CollectionConfigFeatureProviderConfiguration(
        raw_features=_RAW_FEATURES
    )
    return _collectionconfig.CollectionConfigFeatureProvider(config)


def test_provider_conforms_to_protocol(provider):
    assert isinstance(provider, FeatureProviderProtocol)


def test_config_rejects_unknown_fields():
    with pytest.raises(pydantic.ValidationError):
        _collectionconfig.CollectionConfigFeatureProviderConfiguration(
            raw_features=_RAW_FEATURES, unknown_field="whatever"
        )


def test_config_provider_name_defaults_to_collection_config():
    config = _collectionconfig.CollectionConfigFeatureProviderConfiguration(
        raw_features=_RAW_FEATURES
    )
    assert config.provider_name == "collection-config"


@pytest.mark.asyncio
async def test_provider_factory_returns_configured_provider():
    raw_config = {
        "raw_features": [
            {"id": "1", "properties": {"name": "alpha"}, "geometry": "POINT (10 20)"}
        ]
    }
    provider = await _collectionconfig.collection_config_provider_factory(
        collection=None,
        raw_config=raw_config,
        potto_config=PottoSettings(),
    )
    assert isinstance(provider, _collectionconfig.CollectionConfigFeatureProvider)
    assert len(provider.config.raw_features) == 1
    assert provider.config.raw_features[0].id_ == "1"


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
async def test_list_features_returns_expected_properties_and_geometry(provider):
    features = await provider.list_features(PottoFeatureFilter(limit=10, offset=0))
    alpha = next(f for f in features if f.id_ == "1")
    assert alpha.properties == {"name": "alpha", "value": 1}
    assert alpha.geometry.x == pytest.approx(10)
    assert alpha.geometry.y == pytest.approx(20)


@pytest.mark.asyncio
async def test_list_features_reprojects_to_requested_crs(provider):
    # Point(10, 20) in EPSG:4326 → approx (1113194.9, 2273030.9) in EPSG:3857
    feature_filter = PottoFeatureFilter(limit=10, offset=0, crs=_EPSG3857)
    features = await provider.list_features(feature_filter)
    alpha = next(f for f in features if f.id_ == "1")
    assert alpha.geometry.x == pytest.approx(1113194.9, rel=1e-4)
    assert alpha.geometry.y == pytest.approx(2273030.9, rel=1e-4)


@pytest.mark.asyncio
async def test_count_items_returns_matched_and_total(provider):
    result = await provider.count_items()
    assert result.matched == 3
    assert result.total == 3


@pytest.mark.asyncio
async def test_count_items_bbox_affects_matched_but_not_total(provider):
    feature_filter = PottoFeatureFilter(
        limit=10, offset=0, bbox=(5.0, 15.0, 35.0, 45.0)
    )
    result = await provider.count_items(feature_filter)
    assert result.matched == 2
    assert result.total == 3


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
async def test_get_feature_reprojects_to_requested_crs(provider):
    # Point(10, 20) in EPSG:4326 → approx (1113194.9, 2273030.9) in EPSG:3857
    feature = await provider.get_feature("1", crs=_EPSG3857)
    assert feature is not None
    assert feature.geometry.x == pytest.approx(1113194.9, rel=1e-4)
    assert feature.geometry.y == pytest.approx(2273030.9, rel=1e-4)


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
async def test_get_queryables_excludes_geometry_field(provider):
    queryables = await provider.get_queryables()
    geometry_fields = [
        name
        for name, field_schema in queryables["properties"].items()
        if field_schema.get("x-ogc-role") == "primary-geometry"
    ]
    assert geometry_fields == []


@pytest.mark.asyncio
async def test_get_storage_crs_defaults_to_crs84(provider):
    result = await provider.get_storage_crs()
    assert result is not None
    assert result.crs == CRS_84


@pytest.mark.asyncio
async def test_get_storage_crs_returns_configured_crs():
    config = _collectionconfig.CollectionConfigFeatureProviderConfiguration(
        raw_features=_RAW_FEATURES, storage_crs=_EPSG3857
    )
    provider = _collectionconfig.CollectionConfigFeatureProvider(config)
    result = await provider.get_storage_crs()
    assert result is not None
    assert result.crs == _EPSG3857


@pytest.mark.asyncio
async def test_get_spatial_extent_computed_from_feature_geometries(provider):
    extent = await provider.get_spatial_extent()
    assert extent is not None
    assert extent.bbox == [(10.0, 20.0, 50.0, 60.0)]


@pytest.mark.asyncio
async def test_get_spatial_extent_returns_none_when_no_features():
    config = _collectionconfig.CollectionConfigFeatureProviderConfiguration(
        raw_features=[]
    )
    provider = _collectionconfig.CollectionConfigFeatureProvider(config)
    assert await provider.get_spatial_extent() is None


@pytest.mark.asyncio
async def test_get_temporal_extent_returns_none(provider):
    assert await provider.get_temporal_extent() is None


@pytest.mark.asyncio
async def test_get_additional_extents_returns_none(provider):
    assert await provider.get_additional_extents() is None
