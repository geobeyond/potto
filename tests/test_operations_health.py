import pytest
from pydantic import PostgresDsn

from potto.db.alembic_utils import build_alembic_config
from potto.operations.health import check_health

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_check_health_ok(db, settings):
    result = await check_health(build_alembic_config(settings))
    assert result.status == "ok"
    assert result.database == "ok"


@pytest.mark.asyncio
async def test_check_health_outdated_when_schema_missing(sync_db_engine, settings):
    """No ``db`` fixture here - nothing has been created (or stamped) yet."""
    result = await check_health(build_alembic_config(settings))
    assert result.status == "error"
    assert result.database == "outdated"


@pytest.mark.asyncio
async def test_check_health_error_when_db_unreachable(settings):
    settings.database_dsn = PostgresDsn(
        "postgresql+psycopg://potto:pottopass@localhost:1/potto"
    )
    result = await check_health(build_alembic_config(settings))
    assert result.status == "error"
    assert result.database == "error"
