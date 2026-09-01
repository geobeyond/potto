import json
import logging

from pygments import highlight
from pygments.formatters import HtmlFormatter  # ty: ignore
from pygments.lexers import JsonLexer  # ty: ignore
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from ...config import PottoSettings
from ...exceptions import PottoCollectionNotFoundException
from ...schemas.auth import PottoUser
from ...schemas.features import (
    FeatureFilter,
    PottoFeatureFilter,
)

from ...wrapper import Potto

logger = logging.getLogger(__name__)

_PYGMENTS_FORMATTER = HtmlFormatter(style="friendly")


async def list_collections(request: Request) -> Response:
    user = potto_user if isinstance((potto_user := request.user), PottoUser) else None
    settings: PottoSettings = request.state.settings
    potto: Potto = request.state.potto
    async with settings.get_db_session_maker()() as session:
        collections = await potto.list_collections(
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
    user = potto_user if isinstance((potto_user := request.user), PottoUser) else None
    settings: PottoSettings = request.state.settings
    potto: Potto = request.state.potto
    async with settings.get_db_session_maker()() as session:
        potto_response = await potto.get_collection(
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


async def list_collection_items(request: Request) -> Response:
    user = potto_user if isinstance((potto_user := request.user), PottoUser) else None
    settings: PottoSettings = request.state.settings
    potto: Potto = request.state.potto
    # FIXME
    feature_filter = PottoFeatureFilter.from_feature_filter(
        FeatureFilter.from_query_parameters(request.query_params)
    )
    try:
        async with settings.get_db_session_maker()() as session:
            items_response = await potto.list_collection_items(
                request.path_params["collection_id"],
                user=user,
                filter_=feature_filter,
                session=session,
            )
    except PottoCollectionNotFoundException as err:
        raise HTTPException(404, detail="Collection not found") from err
    return request.state.templates.TemplateResponse(
        request,
        "items/list.html",
        context={
            "collection": items_response.collection,
            "items": items_response,
        },
    )
