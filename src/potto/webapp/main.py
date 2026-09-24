import asyncio
import contextlib
import logging
from typing import AsyncIterator

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.routing import (
    Mount,
    Route,
)
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from starlette_babel import LocaleMiddleware

from .. import config
from ..authn.backend import LocalAuthBackend, OIDCAuthBackend
from ..wrapper import Potto
from .middleware import PublicURLMiddleware
from .routes import (
    auth as auth_routes,
    landing as landing_routes,
    ogcapi_features as ogc_api_features_routes,
)
from .state import AppState
from .api.main import create_api_app_from_settings
from .admin.main import create_admin_app_from_settings

logger = logging.getLogger(__name__)


def _log_broker_connect_failure(task: "asyncio.Task[object]") -> None:
    if task.cancelled():
        return
    if (err := task.exception()) is not None:
        logger.error("Internal MQTT broker connection failed", exc_info=err)


@contextlib.asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[AppState]:
    settings: config.PottoSettings = app.state.settings
    oidc_provider = settings.get_oidc_provider()
    if oidc_provider is not None:
        await oidc_provider.get_discovery()
    broker = settings.get_internal_broker(role="api")
    # Connecting to the internal broker must not block API startup or crash it if
    # mosquitto is unreachable - the broker is configured for unlimited reconnect
    # attempts (see config.py's get_internal_broker), so this task keeps retrying
    # in the background for as long as the app runs.
    connect_task = asyncio.create_task(broker.connect())
    connect_task.add_done_callback(_log_broker_connect_failure)
    try:
        yield AppState(
            settings=settings,
            templates=Jinja2Templates(env=settings.get_jinja_env()),
            potto=Potto(settings),
            oidc_provider=oidc_provider,
            authorizer=settings.get_authorizer(),
        )
    finally:
        connect_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await connect_task
        await broker.stop()


def create_app() -> Starlette:
    settings = config.get_settings()
    return create_app_from_settings(settings)


def create_app_from_settings(settings: config.PottoSettings) -> Starlette:
    if settings.static_dir is not None:
        settings.static_dir.mkdir(parents=True, exist_ok=True)
    oidc_provider = settings.get_oidc_provider()
    auth_backend = (
        OIDCAuthBackend(settings, oidc_provider)
        if oidc_provider is not None
        else LocalAuthBackend(settings)
    )
    api_app = create_api_app_from_settings(settings)
    routes = []
    if settings.oidc is not None:
        routes += [
            Route("/auth/oidc/login", auth_routes.oidc_login, name="oidc-login"),
            Route(
                "/auth/oidc/callback", auth_routes.oidc_callback, name="oidc-callback"
            ),
        ]
    routes += [
        Route("/", landing_routes.get_landing_page, name="landing-page"),
        Route("/set-language/{lang}", landing_routes.set_language, name="set_language"),
    ]
    if True:  # whether to enable ogc api features routes: let's make this controllable via server metadata
        routes.extend(
            [
                Route(
                    "/collections/{collection_id}",
                    ogc_api_features_routes.get_collection_details,
                    name="collection-get",
                ),
                Route(
                    "/collections/{collection_id}/items",
                    ogc_api_features_routes.list_collection_items,
                    name="collection-item-list",
                ),
                Route(
                    "/collections",
                    ogc_api_features_routes.list_collections,
                    name="collection-list",
                ),
            ]
        )
    routes.extend(
        [
            Mount("/api", app=api_app, name="api"),
            Mount(
                "/static",
                app=StaticFiles(
                    directory=settings.static_dir,
                    packages=[("potto", "webapp/static"), ("pygeoapi", "static")],
                ),
                name="static",
            ),
        ]
    )
    app = Starlette(
        debug=settings.debug,
        routes=routes,
        middleware=[
            Middleware(PublicURLMiddleware, public_url=str(settings.public_url)),
            Middleware(
                LocaleMiddleware,
                locales=settings.languages,
                default_locale=settings.languages[0],
            ),
            Middleware(
                SessionMiddleware,
                secret_key=settings.session_secret_key.get_secret_value(),
            ),
            Middleware(
                AuthenticationMiddleware,
                backend=auth_backend,
            ),
            Middleware(GZipMiddleware, minimum_size=1000, compresslevel=9),
        ],
        lifespan=lifespan,
    )
    app.state.settings = settings
    admin_app = create_admin_app_from_settings(settings)
    admin_app.mount_to(app)
    return app
