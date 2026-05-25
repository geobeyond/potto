import pytest
import pytest_asyncio
import sqlmodel
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.routing import Mount

from potto import config
from potto.db.commands.auth import create_user
from potto.db.commands.collections import create_collection
from potto.schemas import (
    auth as auth_schemas,
    base as base_schemas,
    collections as collections_schemas,
)
from potto.webapp.main import create_app_from_settings
from potto.webapp.api import dependencies


@pytest.fixture
def settings() -> config.PottoSettings:
    original_settings = config.get_settings()
    original_settings.database_dsn = original_settings.test_database_dsn
    return original_settings


@pytest.fixture
def sync_db_engine(settings: config.PottoSettings):
    yield settings.get_sync_db_engine()


@pytest.fixture
def db_session_maker(settings: config.PottoSettings):
    yield settings.get_db_session_maker()


@pytest.fixture
def db(sync_db_engine):
    """Provides a clean database."""
    sqlmodel.SQLModel.metadata.create_all(sync_db_engine)
    yield
    sqlmodel.SQLModel.metadata.drop_all(sync_db_engine)


@pytest.fixture
def webapp(settings: config.PottoSettings):
    webapp = create_app_from_settings(settings)
    api_webapp = next(
        r.app for r in webapp.routes if isinstance(r, Mount) and r.name == "api"
    )
    api_webapp.dependency_overrides[dependencies.get_settings] = lambda: settings
    yield webapp


@pytest.fixture
def webapp_test_client(webapp):
    with TestClient(webapp) as client:
        yield client


@pytest.fixture
def webapp_test_client_as_admin(webapp, admin_user):
    api_webapp = next(
        r.app for r in webapp.routes if isinstance(r, Mount) and r.name == "api"
    )
    api_webapp.dependency_overrides[dependencies.get_current_user] = lambda: admin_user
    with TestClient(webapp) as client:
        yield client
    api_webapp.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_user(db, db_session_maker):
    async with db_session_maker() as session:
        db_user = await create_user(
            session,
            auth_schemas.UserCreate(
                username="test-admin",
                scopes=[auth_schemas.PottoScope.ADMIN],
                email="test@test.test",
                password=SecretStr("testpass"),
            ),
        )
        yield db_user


@pytest_asyncio.fixture
async def obs_feature_collection(db, db_session_maker, admin_user):
    async with db_session_maker() as session:
        yield await create_collection(
            session,
            collections_schemas.CollectionCreate(
                resource_identifier="obs-test",
                owner_id=admin_user.id,
                is_public=False,
                collection_type=base_schemas.CollectionType.FEATURE_COLLECTION,
                title="Testing obs feature collection",
                spatial_extent="POLYGON ((-122 43, -122 49, -75 49, -75 43, -122 43))",
                spatial_extent_crs="http://www.opengis.net/def/crs/OGC/1.3/CRS84",
                providers={
                    "feature": base_schemas.PottoProvider(
                        provider_name="pygeoapi",
                        config={
                            "python_callable": "potto.pygeoapi_providers.PygeoapiConfigWktFeatureProvider",
                            "options": {},
                            "data": {
                                "features": [
                                    {
                                        "id": 371,
                                        "geometry": "POINT (-75 45)",
                                        "properties": {
                                            "stn_id": 35,
                                            "datetime": "2001-10-30T14:24:55Z",
                                            "value": 89.9,
                                        },
                                    },
                                    {
                                        "id": 377,
                                        "geometry": "POINT (-75 45)",
                                        "properties": {
                                            "stn_id": 35,
                                            "datetime": "2002-10-30T18:31:38Z",
                                            "value": 93.9,
                                        },
                                    },
                                    {
                                        "id": 238,
                                        "geometry": "POINT (-79 43)",
                                        "properties": {
                                            "stn_id": 2147,
                                            "datetime": "2007-10-30T08:57:29Z",
                                            "value": 103.5,
                                        },
                                    },
                                    {
                                        "id": 297,
                                        "geometry": "POINT (-79 43)",
                                        "properties": {
                                            "stn_id": 2147,
                                            "datetime": "2003-10-30T07:37:29Z",
                                            "value": 93.5,
                                        },
                                    },
                                    {
                                        "id": 964,
                                        "geometry": "POINT (-122 49)",
                                        "properties": {
                                            "stn_id": 604,
                                            "datetime": "2000-10-30T18:24:39Z",
                                            "value": 99.9,
                                        },
                                    },
                                ]
                            },
                        },
                    )
                },
            ),
        )
