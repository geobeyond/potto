"""FastAPI app for serving non-HTML responses.

NOTE: We do not use any lifespan-related functionality when setting up this
FastAPI application because the way that it gets used at runtime is by being
mounted by our main starlette-based app. Therefore, lifespan is configured
in the starlette app.
"""

from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2AuthorizationCodeBearer
from starlette.staticfiles import StaticFiles

from ... import (
    config,
    exceptions as potto_exceptions,
)
from ...schemas.auth import PottoUser
from . import dependencies
from .routers import (
    auth,
    base,
    collections,
    items,
)


def _handle_potto_not_found_exception(
    request: Request, err: potto_exceptions.PottoNotFoundException
) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"detail": str(err)},
    )


def create_api_app() -> FastAPI:
    settings = config.get_settings()
    return create_api_app_from_settings(settings)


def create_api_app_from_settings(settings: config.PottoSettings) -> FastAPI:
    app = FastAPI(
        title="Potto",
        summary="OGC API server",
        docs_url=None,
    )
    app.add_exception_handler(
        potto_exceptions.PottoNotFoundException,
        _handle_potto_not_found_exception,  # ty: ignore[invalid-argument-type]
    )

    app.mount(
        "/static",
        StaticFiles(
            directory=settings.static_dir,
            packages=[("potto", "webapp/static")],
        ),
        name="static",
    )
    if settings.oidc is None:
        app.include_router(auth.router)
    else:
        # Replace get_current_user with an OIDC-scheme variant so both the
        # runtime dependency and the OpenAPI security scheme are correct.
        # Auth itself is handled by AuthenticationMiddleware; the scheme here
        # exists for OpenAPI docs and Swagger UI bearer-token support.
        oidc = settings.oidc
        oidc_scheme = OAuth2AuthorizationCodeBearer(
            authorizationUrl=f"{oidc.issuer}/authorize",
            tokenUrl=f"{oidc.issuer}/token",
            auto_error=False,
        )

        async def get_current_user_oidc(
            request: Request,
            _token: Annotated[str | None, Depends(oidc_scheme)],
        ) -> PottoUser | None:
            return request.user if isinstance(request.user, PottoUser) else None

        app.dependency_overrides[dependencies.get_current_user] = get_current_user_oidc

    app.include_router(collections.router)
    app.include_router(items.router)
    app.include_router(base.router)
    return app
