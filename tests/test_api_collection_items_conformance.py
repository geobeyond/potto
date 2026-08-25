"""Regression tests for OGC API - Features conformance issues caught by CITE.

These replicate, at the pytest level, the specific assertions the OGC CITE
ogcapi-features-1.0 test suite makes against `/collections/{id}/items` - so
regressions surface here instead of only in a slow, low-detail CITE run.
"""

import pytest

pytestmark = pytest.mark.integration


def test_bbox_comma_separated_returns_200(
    db, admin_user, obs_feature_collection, webapp_test_client_as_admin
):
    """OGC API - Features requires bbox as a single comma-separated value."""
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}/items"
        "?bbox=-76,44,-74,46"
    )
    assert response.status_code == 200
    ids = {feat["id"] for feat in response.json()["features"]}
    assert ids == {"371", "377"}


def test_bbox_repeated_params_also_returns_200(
    db, admin_user, obs_feature_collection, webapp_test_client_as_admin
):
    """The repeated-key form must keep working alongside the comma-separated one."""
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}/items"
        "?bbox=-76&bbox=44&bbox=-74&bbox=46"
    )
    assert response.status_code == 200
    ids = {feat["id"] for feat in response.json()["features"]}
    assert ids == {"371", "377"}


def test_bbox_with_6_values_returns_200(
    db, admin_user, obs_feature_collection, webapp_test_client_as_admin
):
    """A 3D bbox (with z-min/z-max) is valid per the spec; the z values are ignored."""
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}/items"
        "?bbox=-76,44,0,-74,46,100"
    )
    assert response.status_code == 200
    ids = {feat["id"] for feat in response.json()["features"]}
    assert ids == {"371", "377"}


def test_bbox_with_invalid_number_of_values_returns_400(
    db, admin_user, obs_feature_collection, webapp_test_client_as_admin
):
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}/items"
        "?bbox=-76,44,-74"
    )
    assert response.status_code == 400


def test_unknown_query_parameter_returns_400(
    db, admin_user, obs_feature_collection, webapp_test_client_as_admin
):
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}/items"
        "?not-a-real-parameter=1"
    )
    assert response.status_code == 400


def test_datetime_filter_selects_matching_items(
    db, admin_user, obs_feature_collection, webapp_test_client_as_admin
):
    """Items outside a datetime interval are excluded from the response."""
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}/items"
        "?datetime=2001-01-01T00:00:00Z/2003-12-31T23:59:59Z"
    )
    assert response.status_code == 200
    ids = {feat["id"] for feat in response.json()["features"]}
    assert ids == {"371", "377", "297"}


def test_datetime_filter_supports_open_ended_interval(
    db, admin_user, obs_feature_collection, webapp_test_client_as_admin
):
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}/items"
        "?datetime=2007-01-01T00:00:00Z/.."
    )
    assert response.status_code == 200
    ids = {feat["id"] for feat in response.json()["features"]}
    assert ids == {"238"}


def test_datetime_filter_supports_single_instant(
    db, admin_user, obs_feature_collection, webapp_test_client_as_admin
):
    response = webapp_test_client_as_admin.get(
        f"/api/collections/{obs_feature_collection.resource_identifier}/items"
        "?datetime=2001-10-30T14:24:55Z"
    )
    assert response.status_code == 200
    ids = {feat["id"] for feat in response.json()["features"]}
    assert ids == {"371"}


def test_openapi_declares_bbox_parameter_up_to_six_items(
    db, admin_user, obs_feature_collection, webapp_test_client_as_admin
):
    """bbox may be a 3D bbox (minx,miny,minz,maxx,maxy,maxz) per the spec."""
    response = webapp_test_client_as_admin.get("/api/openapi.json")
    assert response.status_code == 200
    parameters = response.json()["paths"]["/collections/{collection_id}/items"]["get"][
        "parameters"
    ]
    bbox_param = next(p for p in parameters if p["name"] == "bbox")
    assert bbox_param["schema"]["minItems"] == 4
    assert bbox_param["schema"]["maxItems"] == 6
    assert bbox_param["explode"] is False


def test_openapi_declares_datetime_parameter(
    db, admin_user, obs_feature_collection, webapp_test_client_as_admin
):
    response = webapp_test_client_as_admin.get("/api/openapi.json")
    assert response.status_code == 200
    parameters = response.json()["paths"]["/collections/{collection_id}/items"]["get"][
        "parameters"
    ]
    assert any(p["name"] == "datetime" for p in parameters)
