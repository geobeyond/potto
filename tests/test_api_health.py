import pytest

pytestmark = pytest.mark.integration


def test_health_check(db, webapp_test_client):
    response = webapp_test_client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
