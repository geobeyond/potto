from fastapi import (
    APIRouter,
    Request,
)
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse

from ....schemas.web import base

from .. import responses
from ..dependencies import (
    PottoDependency,
    SettingsDependency,
    UserDependency,
)

router = APIRouter()


@router.get("/docs", include_in_schema=False, response_class=HTMLResponse)
async def swagger_ui_html(request: Request) -> HTMLResponse:
    """Returns interactive OpenAPI docs, using the swagger ui template."""
    return get_swagger_ui_html(
        openapi_url=request.scope.get("root_path", "") + request.app.openapi_url,
        title=f"{request.app.title} - Swagger UI",
        swagger_favicon_url=str(
            request.url_for("static", path="/img/potto-favicon.png")
        ),
    )


@router.get(
    "/",
    name="landing-page",
    response_model_exclude_none=True,
    responses=responses.ERROR_RESPONSES,
)
async def landing_page(
    request: Request,
    potto: PottoDependency,
    settings: SettingsDependency,
    user: UserDependency,
) -> base.JsonLanding:
    """API landing page."""
    result = await potto.api_get_landing_page(user=user)
    return base.JsonLanding.from_potto(
        result, request.url_for, oidc_configured=settings.oidc is not None
    )


@router.get(
    "/conformance", name="conformance-page", responses=responses.ERROR_RESPONSES
)
async def conformance_page(potto: PottoDependency) -> base.JsonConformance:
    """OGC API conformance information."""
    result = await potto.api_get_conformance_details()
    return base.JsonConformance(conforms_to=result.conforms_to)
