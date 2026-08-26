import pytest

pytestmark = pytest.mark.integration


def test_api_collection_item_list_body(
    db,
    admin_user,
    obs_feature_collection,
    webapp_test_client_as_admin,
):
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}/items"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "FeatureCollection"
    features = payload["features"]
    assert len(features) == len(
        obs_feature_collection.providers["feature"]["config"]["raw_features"]
    )


def test_api_collection_item_list_headers(
    db,
    admin_user,
    obs_feature_collection,
    webapp_test_client_as_admin,
):
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}/items"
    )
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/geo+json"
    assert "link" in response.headers


def test_api_collection_item_list_links(
    db,
    admin_user,
    obs_feature_collection,
    webapp_test_client_as_admin,
):
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}/items"
    )
    assert response.status_code == 200
    links = response.json()["links"]
    home_link = [li for li in links if li["rel"] == "home"][0]
    assert home_link["type"] == "application/json"
    assert home_link["href"].endswith("/api/")
    self_link = [li for li in links if li["rel"] == "self"][0]
    assert self_link["type"] == "application/geo+json"
    assert self_link["href"].endswith(
        f"/api/collections/{obs_feature_collection.resource_identifier}/items"
    )
    collection_link = [li for li in links if li["rel"] == "collection"][0]
    assert collection_link["type"] == "application/json"
    assert collection_link["href"].endswith(
        f"/api/collections/{obs_feature_collection.resource_identifier}"
    )


def test_api_collection_item_get_body(
    db,
    admin_user,
    obs_feature_collection,
    webapp_test_client_as_admin,
):
    first_feature = obs_feature_collection.providers["feature"]["config"][
        "raw_features"
    ][0]
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}/items/{first_feature['id']}"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "Feature"


def test_api_collection_item_get_headers(
    db,
    admin_user,
    obs_feature_collection,
    webapp_test_client_as_admin,
):
    first_feature = obs_feature_collection.providers["feature"]["config"][
        "raw_features"
    ][0]
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}/items/{first_feature['id']}"
    )
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/geo+json"
    assert "link" in response.headers


def test_api_collection_item_get_links(
    db,
    admin_user,
    obs_feature_collection,
    webapp_test_client_as_admin,
):
    first_feature = obs_feature_collection.providers["feature"]["config"][
        "raw_features"
    ][0]
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}/items/{first_feature['id']}"
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["links"]) > 0
