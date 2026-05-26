import logging

import babel
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import (
    RedirectResponse,
    Response,
)

from ...config import PottoSettings
from ...wrapper import Potto
from ...schemas import auth as auth_schemas

logger = logging.getLogger(__name__)


async def get_landing_page(request: Request) -> Response:
    user = (
        potto_user
        if isinstance((potto_user := request.user), auth_schemas.PottoUser)
        else None
    )
    potto: Potto = request.state.potto
    return request.state.templates.TemplateResponse(
        request,
        "landing-page.html",
        context={"contents": await potto.get_overview(user=user)},
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
