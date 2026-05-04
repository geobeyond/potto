"""FastAPI app for serving non-HTML responses.

NOTE: We do not use any lifespan-related functionality when setting up this
FastAPI application because the way that it gets used at runtime is by being
mounted by our main starlette-based app. Therefore, lifespan is configured
in the starlette app.
"""

import asyncio
import concurrent.futures
from typing import (
    Annotated,
    Any,
    cast,
)

from fastapi import (
    Depends,
    FastAPI,
    Request,
)
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2AuthorizationCodeBearer
from starlette.staticfiles import StaticFiles

from ... import (
    config,
    exceptions as potto_exceptions,
)
from ...operations.metadata import get_server_metadata
from ...schemas.auth import PottoUser
from ...schemas.potto import ServerMetadata
from . import (
    dependencies,
    tags,
)
from .routers import (
    auth,
    base,
    collections,
    items,
)


async def _fetch_api_metadata(settings: config.PottoSettings) -> ServerMetadata:
    """
    Small helper to allow retrieving server metadata from a sync context.

    This function only exists so that we can retrieve the metadata and use it when
    creating the OpenAPI document below, when the FastAPI app is created.
    """
    async with settings.get_db_session_maker()() as session:
        db_server_metadata = await get_server_metadata(session)
    return db_server_metadata.to_potto()


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
    # asyncio.run() fails if called from a running event loop (e.g. uvicorn calls
    # the app factory from within its own loop). Running in a new thread guarantees
    # a fresh event loop regardless of the caller's async context.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        api_metadata: ServerMetadata = cast(
            ServerMetadata,
            pool.submit(asyncio.run, _fetch_api_metadata(settings)).result(),
        )
    raw_title = api_metadata.title
    app_title = (
        raw_title.get("en") or next(iter(raw_title.values()))
        if isinstance(raw_title, dict)
        else raw_title
    )
    raw_description = api_metadata.description
    app_description = (
        raw_description.get("en") or next(iter(raw_description.values()))
        if isinstance(raw_description, dict)
        else raw_description
    )
    poc = api_metadata.point_of_contact
    contact = {
        "name": (poc.name if poc is not None else None) or "unknown",
        "email": (poc.email if poc is not None else None) or "unknown@unknown.invalid",
        "url": (poc.url if poc is not None else None) or str(settings.public_url),
    }
    lic = api_metadata.license
    license_info = {
        "name": lic.name if lic is not None else "unknown",
        "url": lic.url if lic is not None and lic.url else str(settings.public_url),
    }
    app = FastAPI(
        title=app_title or "potto",
        description=app_description or "unknown",
        contact=contact,
        license_info=license_info,
        openapi_tags=tags.OPENAPI_TAGS,
        summary="OGC API server",
        docs_url=None,
        servers=[{"url": f"{settings.public_url}/api"}],
        root_path_in_servers=False,
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

    _original_openapi = app.openapi

    def _openapi_with_jwt_description() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = _original_openapi()
        for scheme in schema.get("components", {}).get("securitySchemes", {}).values():
            if scheme.get("type") == "oauth2" and "description" not in scheme:
                scheme["description"] = (
                    "OAuth2 bearer token. The access token is a JSON Web Token (JWT) "
                    "that conforms to RFC8725."
                )
        return schema

    app.openapi = _openapi_with_jwt_description  # ty: ignore[invalid-assignment]
    return app
