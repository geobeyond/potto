import pytest
import sqlalchemy

pytestmark = pytest.mark.integration


def test_health_check(db, webapp_test_client):
    response = webapp_test_client.get("/api/health")
    assert response.status_code == 200
    # mosquitto isn't running in this test environment, so the broker never connects -
    # this itself verifies broker unreachability doesn't fail the overall health check.
    assert response.json() == {
        "status": "ok",
        "collection_manager": "ok",
        "internal_broker": "error",
    }


def test_health_check_outdated_schema(db, sync_db_engine, webapp_test_client):
    """A DB that isn't stamped at the migrations head is reported as unhealthy."""
    with sync_db_engine.connect() as connection:
        connection.execute(sqlalchemy.text("DELETE FROM alembic_version"))
        connection.commit()

    response = webapp_test_client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "collection_manager": "not-ready",
        "internal_broker": "error",
    }
