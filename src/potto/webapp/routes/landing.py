import logging

import babel
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import (
    RedirectResponse,
    Response,
)

from ...config import PottoSettings
from ...wrapper import Potto
from ...schemas import auth as auth_schemas
from ...schemas.web.system import WebHealthCheck

logger = logging.getLogger(__name__)


async def get_landing_page(request: Request) -> Response:
    user = (
        potto_user
        if isinstance((potto_user := request.user), auth_schemas.PottoUser)
        else None
    )
    potto: Potto = request.state.potto
    health = await potto.get_health_status()
    contents = None
    if health.status == "ok":
        try:
            contents = await potto.get_overview(user=user)
        except SQLAlchemyError:
            # health check just passed, but the DB dropped before this next
            # query - fall back to the same banner rendering rather than
            # letting this 500.
            health = WebHealthCheck(status="error", database="error")
    return request.state.templates.TemplateResponse(
        request,
        "landing-page.html",
        context={"contents": contents, "health": health},
    )


async def set_language(request: Request):
    settings: PottoSettings = request.state.settings
    lang = request.path_params["lang"]
    logger.debug(f"{lang=}")
    if lang not in settings.languages:
        raise HTTPException(status_code=400, detail=f"Invalid language: {lang}")
    next_url = request.headers.get("referer", request.url_for("home"))
    response = RedirectResponse(next_url)
    try:
        babel.Locale.parse(lang)
        response.set_cookie("language", lang)
    except babel.UnknownLocaleError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return response
