import alembic.command
import pytest
import pytest_asyncio
import sqlalchemy
import sqlmodel
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.routing import Mount

from playwright.sync_api import expect
from potto import config
from potto.authz.backend import LocalAuthorizationBackend
from potto.db.alembic_utils import build_alembic_config
from potto.db.commands.auth import create_user
from potto.operations.collections import create_collection
from potto.schemas import (
    auth as auth_schemas,
    base as base_schemas,
    collections as collections_schemas,
)
from potto.webapp.main import create_app_from_settings
from potto.webapp.api import dependencies

pytest_plugins = ("live_server",)

# This module deals with playwright tracing options manually because some
# tests need the `authenticated_context` fixture, which creates a new
# browser context different from the default one.
_TRACING_VALUES = ("on", "retain-on-failure")


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
def db(sync_db_engine, settings):
    """Provides a clean database.

    Also stamps the alembic version table at ``head`` - the tables are
    created directly from the current models rather than by running actual
    migrations, but this keeps alembic's own bookkeeping consistent with
    that, which the health check relies on.
    """
    sqlmodel.SQLModel.metadata.create_all(sync_db_engine)
    alembic.command.stamp(build_alembic_config(settings), "head")
    yield
    sqlmodel.SQLModel.metadata.drop_all(sync_db_engine)
    with sync_db_engine.connect() as connection:
        connection.execute(sqlalchemy.text("DROP TABLE IF EXISTS alembic_version"))
        connection.commit()


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


@pytest.fixture(scope="session")
def authenticated_context(browser, auth_credentials, base_url, request):
    context = browser.new_context(base_url=base_url)

    if (tracing_value := request.config.getoption("--tracing")) in _TRACING_VALUES:
        context.tracing.start(screenshots=True, snapshots=True, sources=True)

    page = context.new_page()

    try:
        page.goto("/")
        page.get_by_role("link", name="login").click()
        username, password = auth_credentials
        page.get_by_role("textbox", name="username").fill(username)
        page.get_by_role("textbox", name="password").fill(password)
        page.get_by_role("button", name="sign in").click()

        page.wait_for_url("/")
        expect(page.get_by_role("link", name="login")).not_to_be_visible()
        user_menu = page.locator("#user-menu-toggle")
        expect(user_menu).to_be_visible()

        user_menu.click()
        expect(page.get_by_text(username)).to_be_visible()

        storage_state = context.storage_state()

        if tracing_value in _TRACING_VALUES:
            context.tracing.stop()

    except:
        if tracing_value in _TRACING_VALUES:
            trace_path = "test-results/auth-setup-trace.zip"
            context.tracing.stop(path=trace_path)
        raise
    finally:
        page.close()
        context.close()

    yield storage_state


@pytest.fixture(scope="function")
def authenticated_page(browser, authenticated_context, base_url, request):
    context = browser.new_context(
        storage_state=authenticated_context, base_url=base_url
    )

    if (tracing_value := request.config.getoption("--tracing")) in _TRACING_VALUES:
        context.tracing.start(screenshots=True, snapshots=True, sources=True)

    page = context.new_page()
    yield page

    if tracing_value in _TRACING_VALUES:
        if tracing_value == "on" or (
            tracing_value == "retain-on-failure" and request.node.rep_call.failed
        ):
            trace_path = f"test-results/{request.node.name}-trace.zip"
            context.tracing.stop(path=trace_path)
        else:
            context.tracing.stop()
    context.close()


@pytest.fixture(scope="function")
def fresh_authenticated_page(browser, auth_credentials, base_url):
    context = browser.new_context(base_url=base_url)
    page = context.new_page()

    page.goto("/")
    page.get_by_role("link", name="login").click()
    username, password = auth_credentials
    page.get_by_role("textbox", name="username").fill(username)
    page.get_by_role("textbox", name="password").fill(password)
    page.get_by_role("button", name="sign in").click()

    page.wait_for_url("/")
    expect(page.get_by_role("link", name="login")).not_to_be_visible()
    user_menu = page.locator("#user-menu-toggle")
    expect(user_menu).to_be_visible()

    user_menu.click()
    expect(page.get_by_text(username)).to_be_visible()

    yield page
    context.close()


@pytest_asyncio.fixture
async def obs_feature_collection(db, db_session_maker, admin_user, settings):
    async with db_session_maker() as session:
        yield await create_collection(
            session,
            admin_user,
            LocalAuthorizationBackend(),
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
                        provider_name="collection-config",
                        config={
                            "datetime_field": "datetime",
                            "raw_features": [
                                {
                                    "id": "371",
                                    "geometry": "POINT (-75 45)",
                                    "properties": {
                                        "stn_id": 35,
                                        "datetime": "2001-10-30T14:24:55Z",
                                        "value": 89.9,
                                    },
                                },
                                {
                                    "id": "377",
                                    "geometry": "POINT (-75 45)",
                                    "properties": {
                                        "stn_id": 35,
                                        "datetime": "2002-10-30T18:31:38Z",
                                        "value": 93.9,
                                    },
                                },
                                {
                                    "id": "238",
                                    "geometry": "POINT (-79 43)",
                                    "properties": {
                                        "stn_id": 2147,
                                        "datetime": "2007-10-30T08:57:29Z",
                                        "value": 103.5,
                                    },
                                },
                                {
                                    "id": "297",
                                    "geometry": "POINT (-79 43)",
                                    "properties": {
                                        "stn_id": 2147,
                                        "datetime": "2003-10-30T07:37:29Z",
                                        "value": 93.5,
                                    },
                                },
                                {
                                    "id": "964",
                                    "geometry": "POINT (-122 49)",
                                    "properties": {
                                        "stn_id": 604,
                                        "datetime": "2000-10-30T18:24:39Z",
                                        "value": 99.9,
                                    },
                                },
                            ],
                        },
                    )
                },
            ),
            settings,
        )
