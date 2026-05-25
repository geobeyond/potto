import json
import logging

from pygments import highlight
from pygments.formatters import HtmlFormatter  # ty: ignore
from pygments.lexers import JsonLexer  # ty: ignore
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from ...config import PottoSettings
from ...schemas import auth as auth_schemas

from ...wrapper import Potto

logger = logging.getLogger(__name__)

_PYGMENTS_FORMATTER = HtmlFormatter(style="friendly")


async def list_collections(request: Request) -> Response:
    user = (
        potto_user
        if isinstance((potto_user := request.user), auth_schemas.PottoUser)
        else None
    )
    settings: PottoSettings = request.state.settings
    potto: Potto = request.state.potto
    async with settings.get_db_session_maker()() as session:
        collections = await potto.api_list_collections(
            user=user,
            session=session,
            page=int(request.query_params.get("page", 1)),
            page_size=int(request.query_params.get("page_size", 20)),
        )
    return request.state.templates.TemplateResponse(
        request,
        "collections/list.html",
        context={
            "contents": collections,
        },
    )


async def get_collection_details(request: Request) -> Response:
    user = (
        potto_user
        if isinstance((potto_user := request.user), auth_schemas.PottoUser)
        else None
    )
    settings: PottoSettings = request.state.settings
    potto: Potto = request.state.potto
    async with settings.get_db_session_maker()() as session:
        potto_response = await potto.api_get_collection(
            request.path_params["collection_id"],
            user=user,
            session=session,
            include_queryables=True,
            include_schema=True,
        )
    if potto_response is None:
        raise HTTPException(404, detail="Collection not found")
    queryables_html = (
        highlight(
            json.dumps(potto_response.queryables, indent=2),
            JsonLexer(),
            _PYGMENTS_FORMATTER,
        )
        if potto_response.queryables
        else None
    )
    schema_html = (
        highlight(
            json.dumps(potto_response.schema, indent=2),
            JsonLexer(),
            _PYGMENTS_FORMATTER,
        )
        if potto_response.schema
        else None
    )
    return request.state.templates.TemplateResponse(
        request,
        "collections/detail.html",
        context={
            "contents": potto_response,
            "queryables_html": queryables_html,
            "schema_html": schema_html,
            "pygments_css": _PYGMENTS_FORMATTER.get_style_defs(".highlight"),
        },
    )
