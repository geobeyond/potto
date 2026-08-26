import json

import pytest

pytestmark = pytest.mark.integration


def test_api_collection_list_body(
    db,
    admin_user,
    obs_feature_collection,
    webapp_test_client_as_admin,
):
    response = webapp_test_client_as_admin.get("/api/collections")
    assert response.status_code == 200
    assert (
        response.json()["collections"][0]["id"]
        == obs_feature_collection.resource_identifier
    )


def test_api_collection_list_headers(
    db,
    admin_user,
    obs_feature_collection,
    webapp_test_client_as_admin,
):
    response = webapp_test_client_as_admin.get("/api/collections")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert "link" in response.headers


def test_api_collection_list_links(
    db,
    admin_user,
    obs_feature_collection,
    webapp_test_client_as_admin,
):
    response = webapp_test_client_as_admin.get("/api/collections")
    assert response.status_code == 200
    payload = response.json()
    links = payload["links"]
    home_link = [li for li in links if li["rel"] == "home"][0]
    assert home_link["type"] == "application/json"
    assert home_link["href"].endswith("/api/")
    self_link = [li for li in links if li["rel"] == "self"][0]
    assert self_link["type"] == "application/json"
    assert self_link["href"].endswith("/api/collections")


def test_api_collection_get_body(
    db,
    admin_user,
    obs_feature_collection,
    webapp_test_client_as_admin,
):
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == obs_feature_collection.resource_identifier
    assert payload["itemType"] == "feature"


def test_api_collection_get_headers(
    db,
    admin_user,
    obs_feature_collection,
    webapp_test_client_as_admin,
):
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}"
    )
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert "link" in response.headers


def test_api_collection_get_oapif_part2(
    db,
    admin_user,
    obs_feature_collection,
    webapp_test_client_as_admin,
):
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}"
    )
    assert response.status_code == 200
    payload = response.json()
    print(f"{json.dumps(payload, indent=2)}")
    assert payload["id"] == obs_feature_collection.resource_identifier
    assert "http://www.opengis.net/def/crs/OGC/1.3/CRS84" in payload["crs"]
    assert payload["storageCrs"] == "http://www.opengis.net/def/crs/OGC/1.3/CRS84"


def test_api_collection_get_links(
    db,
    admin_user,
    obs_feature_collection,
    webapp_test_client_as_admin,
):
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == obs_feature_collection.resource_identifier
    links = payload["links"]
    home_link = [li for li in links if li["rel"] == "home"][0]
    assert home_link["type"] == "application/json"
    assert home_link["href"].endswith("/api/")
    self_link = [li for li in links if li["rel"] == "self"][0]
    assert self_link["type"] == "application/json"
    assert self_link["href"].endswith(
        f"/api/collections/{obs_feature_collection.resource_identifier}"
    )
    items_link = [li for li in links if li["rel"] == "items"][0]
    assert items_link["type"] == "application/geo+json"
    assert items_link["href"].endswith(
        f"/api/collections/{obs_feature_collection.resource_identifier}/items"
    )
    schema_link = [
        li
        for li in links
        if li["rel"] == "http://www.opengis.net/def/rel/ogc/1.0/schema"
    ][0]
    assert schema_link["type"] == "application/schema+json"
    assert schema_link["href"].endswith(
        f"/api/collections/{obs_feature_collection.resource_identifier}/schema"
    )
    queryables_link = [
        li
        for li in links
        if li["rel"] == "http://www.opengis.net/def/rel/ogc/1.0/queryables"
    ][0]
    assert queryables_link["type"] == "application/schema+json"
    assert queryables_link["href"].endswith(
        f"/api/collections/{obs_feature_collection.resource_identifier}/queryables"
    )


def test_api_collection_get_schema_body(
    db,
    admin_user,
    obs_feature_collection,
    webapp_test_client_as_admin,
):
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}/schema"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["$id"].endswith(
        f"/api/collections/{obs_feature_collection.resource_identifier}"
    )
    assert payload["type"] == "object"
    assert payload["properties"]["datetime"]["type"] == "string"
    assert payload["properties"]["stn_id"]["type"] == "integer"
    assert payload["properties"]["value"]["type"] == "number"
    assert payload["properties"]["geometry"]["format"] == "geometry-any"
    assert payload["properties"]["geometry"]["x-ogc-role"] == "primary-geometry"


def test_api_collection_get_schema_headers(
    db,
    admin_user,
    obs_feature_collection,
    webapp_test_client_as_admin,
):
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}/schema"
    )
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/schema+json"
    assert "link" in response.headers


def test_api_collection_get_queryables_body(
    db,
    admin_user,
    obs_feature_collection,
    webapp_test_client_as_admin,
):
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}/queryables"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["$id"].endswith(
        f"/api/collections/{obs_feature_collection.resource_identifier}"
    )
    assert payload["type"] == "object"
    assert payload["properties"]["datetime"]["type"] == "string"
    assert payload["properties"]["stn_id"]["type"] == "integer"
    assert payload["properties"]["value"]["type"] == "number"
    assert "geometry" not in payload["properties"]


def test_api_collection_get_queryables_headers(
    db,
    admin_user,
    obs_feature_collection,
    webapp_test_client_as_admin,
):
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}/queryables"
    )
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/schema+json"
    assert "link" in response.headers
