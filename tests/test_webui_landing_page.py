import pytest

from potto.schemas.base import PottoHealthCheck
from potto.wrapper import Potto

pytestmark = pytest.mark.integration


def test_landing_page_healthy(db, webapp_test_client):
    response = webapp_test_client.get("/")

    assert response.status_code == 200
    assert "database problem" not in response.text
    assert "schema is out of date" not in response.text
    assert '<h2 class="mb-0">Collections</h2>' in response.text


def test_landing_page_outdated_schema(db, webapp_test_client, monkeypatch):
    async def fake_get_health_status(self):
        return PottoHealthCheck(status="error", database="outdated")

    monkeypatch.setattr(Potto, "get_health_status", fake_get_health_status)

    response = webapp_test_client.get("/")

    assert response.status_code == 200
    assert "schema is out of date" in response.text
    assert '<h2 class="mb-0">Collections</h2>' not in response.text


def test_landing_page_db_unreachable(db, webapp_test_client, monkeypatch):
    async def fake_get_health_status(self):
        return PottoHealthCheck(status="error", database="error")

    monkeypatch.setattr(Potto, "get_health_status", fake_get_health_status)

    response = webapp_test_client.get("/")

    assert response.status_code == 200
    assert "database problem" in response.text
    assert '<h2 class="mb-0">Collections</h2>' not in response.text
