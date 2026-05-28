import pytest

from potto.config import PottoSettings
from potto.constants import CRS_84
from potto.providers.features import _pygeoapi
from potto.schemas import auth, base
from potto.schemas.potto import Collection

_EPSG3857 = "http://www.opengis.net/def/crs/EPSG/0/3857"


@pytest.fixture
def provider_config():
    return _pygeoapi.PygeoapiFeatureProviderConfig(
        python_callable="potto.pygeoapi_providers.PygeoapiConfigWktFeatureProvider",
        data={
            "features": [
                {"id": 1, "geometry": "POINT (10 20)", "properties": {"name": "alpha"}},
                {"id": 2, "geometry": "POINT (30 40)", "properties": {"name": "beta"}},
                {"id": 3, "geometry": "POINT (50 60)", "properties": {"name": "gamma"}},
            ]
        },
        options={},
    )


@pytest.fixture
def collection():
    return Collection(
        type_=base.CollectionType.FEATURE_COLLECTION,
        identifier="test-collection",
        title="Test Collection",
        owner=auth.PottoUser(id="user-1", username="testuser", is_active=True),
        providers={
            base.ProvidedDataType.FEATURE.value: base.PottoProvider(
                provider_name="pygeoapi",
                config={},
            )
        },
    )


@pytest.fixture
def pygeoapi_api(collection, provider_config):
    return _pygeoapi._get_pygeoapi_api(collection, provider_config, PottoSettings())


@pytest.fixture
def provider_config_with_crs():
    return _pygeoapi.PygeoapiFeatureProviderConfig(
        python_callable="potto.pygeoapi_providers.PygeoapiConfigWktFeatureProvider",
        data={
            "features": [
                {"id": 1, "geometry": "POINT (10 20)", "properties": {"name": "alpha"}},
                {"id": 2, "geometry": "POINT (30 40)", "properties": {"name": "beta"}},
                {"id": 3, "geometry": "POINT (50 60)", "properties": {"name": "gamma"}},
            ]
        },
        options={"storage_crs": CRS_84, "crs": [CRS_84, _EPSG3857]},
    )


@pytest.fixture
def pygeoapi_api_with_crs(collection, provider_config_with_crs):
    return _pygeoapi._get_pygeoapi_api(
        collection, provider_config_with_crs, PottoSettings()
    )


def test_to_potto_feature_integer_id_is_stringified():
    feature = _pygeoapi.to_potto_feature(
        {
            "id": 42,
            "geometry": {"type": "Point", "coordinates": [10.0, 20.0]},
            "properties": {"name": "alpha"},
        }
    )
    assert feature.id_ == "42"


def test_to_potto_feature_id_property_excluded_from_properties():
    feature = _pygeoapi.to_potto_feature(
        {
            "id": "feat-1",
            "geometry": {"type": "Point", "coordinates": [10.0, 20.0]},
            "properties": {"id": "feat-1", "name": "alpha"},
        }
    )
    assert "id" not in feature.properties
    assert "name" in feature.properties


def test_list_features_returns_all_features(collection, pygeoapi_api):
    features = _pygeoapi._list_features(collection, pygeoapi_api, None)
    assert len(features) == 3


def test_list_features_limit_is_respected(collection, pygeoapi_api):
    feature_filter = base.PottoFeatureFilter(limit=2, offset=0)
    features = _pygeoapi._list_features(collection, pygeoapi_api, feature_filter)
    assert len(features) == 2


def test_list_features_bbox_excludes_out_of_range_points(collection, pygeoapi_api):
    # Points at [10,20], [30,40], [50,60] — bbox covers only the first two
    feature_filter = base.PottoFeatureFilter(
        limit=10, offset=0, bbox=(5.0, 15.0, 35.0, 45.0)
    )
    features = _pygeoapi._list_features(collection, pygeoapi_api, feature_filter)
    assert len(features) == 2


def test_count_items_returns_total_matched(collection, pygeoapi_api):
    result = _pygeoapi._count_items(collection, pygeoapi_api, None)
    assert result.matched == 3


def test_count_items_bbox_affects_matched_count(collection, pygeoapi_api):
    feature_filter = base.PottoFeatureFilter(
        limit=10, offset=0, bbox=(5.0, 15.0, 35.0, 45.0)
    )
    result = _pygeoapi._count_items(collection, pygeoapi_api, feature_filter)
    assert result.matched == 2


def test_get_feature_returns_correct_feature(collection, pygeoapi_api):
    result = _pygeoapi._get_feature(collection, pygeoapi_api, "1")
    assert result.id_ == "1"
    assert result.properties["name"] == "alpha"


def test_get_feature_returns_none_for_nonexistent_id(collection, pygeoapi_api):
    assert _pygeoapi._get_feature(collection, pygeoapi_api, "9999") is None


def test_list_features_reprojects_to_requested_crs(collection, pygeoapi_api_with_crs):
    # Point(10, 20) in CRS84 → approx (1113194.9, 2273030.9) in EPSG:3857
    feature_filter = base.PottoFeatureFilter(limit=10, offset=0, crs=_EPSG3857)
    features = _pygeoapi._list_features(
        collection, pygeoapi_api_with_crs, feature_filter
    )
    first_geom = features[0].geometry
    assert first_geom.x == pytest.approx(1113194.9, rel=1e-4)
    assert first_geom.y == pytest.approx(2273030.9, rel=1e-4)


def test_get_feature_reprojects_to_requested_crs(collection, pygeoapi_api_with_crs):
    # Point(10, 20) in CRS84 → approx (1113194.9, 2273030.9) in EPSG:3857
    feature = _pygeoapi._get_feature(
        collection, pygeoapi_api_with_crs, "1", crs=_EPSG3857
    )
    assert feature is not None
    assert feature.geometry.x == pytest.approx(1113194.9, rel=1e-4)
    assert feature.geometry.y == pytest.approx(2273030.9, rel=1e-4)


@pytest.mark.asyncio
async def test_provider_get_storage_crs_returns_none_when_not_configured(
    collection, provider_config
):
    provider = _pygeoapi.PygeoapiFeatureProvider(
        collection, provider_config, PottoSettings()
    )
    assert await provider.get_storage_crs() is None


@pytest.mark.asyncio
async def test_provider_get_storage_crs_returns_configured_crs(collection):
    config = _pygeoapi.PygeoapiFeatureProviderConfig(
        python_callable="potto.pygeoapi_providers.PygeoapiConfigWktFeatureProvider",
        data={"features": []},
        options={"storage_crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
    )
    provider = _pygeoapi.PygeoapiFeatureProvider(collection, config, PottoSettings())
    result = await provider.get_storage_crs()
    assert result is not None
    assert result.crs == "http://www.opengis.net/def/crs/EPSG/0/4326"
