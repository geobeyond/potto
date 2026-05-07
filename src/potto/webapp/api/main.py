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
from fastapi.exceptions import RequestValidationError
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


def _fix_oas30_nullable(obj: Any) -> None:
    """Convert Pydantic v2 / OAS 3.1 nullable schemas to OAS 3.0 nullable:true in-place.

    Pydantic v2 represents Optional[X] as anyOf:[X, {type:null}], which is valid OAS 3.1
    but not OAS 3.0. OGC API Features requires OAS 3.0, so we post-process the schema.
    """
    if isinstance(obj, dict):
        if "anyOf" in obj:
            non_null = [s for s in obj["anyOf"] if s != {"type": "null"}]
            if len(non_null) < len(obj["anyOf"]):
                del obj["anyOf"]
                if len(non_null) == 1:
                    sole = non_null[0]
                    if "$ref" in sole:
                        obj["allOf"] = [sole]
                    else:
                        obj.update(sole)
                elif len(non_null) > 1:
                    obj["anyOf"] = non_null
                obj["nullable"] = True
        for v in list(obj.values()):
            _fix_oas30_nullable(v)
    elif isinstance(obj, list):
        for item in obj:
            _fix_oas30_nullable(item)


def _fix_vendor_specific_parameters(schema: dict[str, Any]) -> None:
    """Rename extra_properties to vendorSpecificParameters per OGC API spec.

    The OGC API spec allows servers to declare a free-form catch-all parameter so that
    unknown query params are explicitly supported rather than triggering a 400. The
    generated name 'extra_properties' doesn't follow that convention; rename it and
    ensure the schema has additionalProperties: true.
    """
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for param in operation.get("parameters", []):
                if (
                    param.get("name") == "extra_properties"
                    and param.get("in") == "query"
                ):
                    param["name"] = "vendorSpecificParameters"
                    param["schema"] = {"type": "object"}
                    param["style"] = "form"


def _fix_limit_parameter_maximum(schema: dict[str, Any], page_size_max: int) -> None:
    """Set maximum on the limit query parameter from server settings."""
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for param in operation.get("parameters", []):
                if param.get("name") == "limit" and param.get("in") == "query":
                    param.setdefault("schema", {})["maximum"] = page_size_max


def _fix_array_query_param_explode(schema: dict[str, Any]) -> None:
    """Set explode:false on the bbox query parameter.

    Without this, OAS clients default to explode:true (repeated keys like
    bbox=-1.5&bbox=50) instead of the comma-separated form the server expects.
    """
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for param in operation.get("parameters", []):
                if param.get("in") == "query" and param.get("name") == "bbox":
                    param["explode"] = False


def _fix_oas30_query_param_style(schema: dict[str, Any]) -> None:
    """Add style:form to query parameters that omit it.

    OAS 3.0 defaults query params to style:form, but the OGC API Features CITE
    test explicitly checks for the property's presence rather than relying on the default.
    """
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for param in operation.get("parameters", []):
                if param.get("in") == "query" and "style" not in param:
                    param["style"] = "form"


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


def _handle_request_validation_error(
    request: Request, err: RequestValidationError
) -> JSONResponse:
    # OGC API requires 400 for invalid/unknown query parameters; FastAPI defaults to 422
    return JSONResponse(status_code=400, content={"detail": err.errors()})


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
        "email": (poc.email if poc is not None else None) or "unknown@example.com",
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
    app.add_exception_handler(
        RequestValidationError,
        _handle_request_validation_error,  # ty: ignore[invalid-argument-type]
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
        _fix_vendor_specific_parameters(schema)
        _fix_limit_parameter_maximum(schema, settings.page_size_max)
        _fix_array_query_param_explode(schema)
        if settings.use_oas30_fixes:
            _fix_oas30_nullable(schema)
            _fix_oas30_query_param_style(schema)
            schema["openapi"] = "3.0.3"
        return schema

    app.openapi = _openapi_with_jwt_description  # ty: ignore[invalid-assignment]
    return app
