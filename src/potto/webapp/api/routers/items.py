import logging
from typing import Annotated

import babel
from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import JSONResponse

from .... import constants
from ....schemas.base import FeatureFilter
from ....schemas.web.items import (
    GeoJsonItem,
    GeoJsonItemCollection,
)
from .. import (
    responses,
    tags,
)
from ..dependencies import (
    CollectionIdPath,
    ItemIdPath,
    LocaleDependency,
    PottoDependency,
    SettingsDependency,
    UserDependency,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/collections/{collection_id}/items",
    name="collection-item-list",
    tags=[tags.ITEMS],
    responses=responses.ERROR_RESPONSES,
)
async def list_collection_items(
    request: Request,
    collection_id: CollectionIdPath,
    filter_: Annotated[FeatureFilter, Query()],
    potto: PottoDependency,
    user: UserDependency,
    locale: LocaleDependency,
    settings: SettingsDependency,
):
    """List collection items."""
    if filter_.__pydantic_extra__:
        unknown = ", ".join(sorted(filter_.__pydantic_extra__))
        raise HTTPException(
            status_code=400, detail=f"Unknown query parameters: {unknown}"
        )
    async with settings.get_db_session_maker()() as session:
        collection_items = await potto.api_list_collection_items(
            collection_id, user=user, locale=locale, filter_=filter_, db_session=session
        )
    result = GeoJsonItemCollection.from_potto(collection_items, request.url_for)
    response_headers: dict[str, str] = {
        "Content-Type": constants.MEDIA_TYPE_GEO_JSON,
        "Link": ",".join((li.serialize_as_http_header() for li in result.links)),
    }
    if crs_header := (
        collection_items.metadata.get("Content-Crs")
        if collection_items.metadata
        else None
    ):
        response_headers["Content-Crs"] = crs_header
    return JSONResponse(
        result.model_dump(exclude_none=True, by_alias=True),
        headers=response_headers,
    )


@router.get(
    "/collections/{collection_id}/items/{item_id}",
    name="collection-item-get",
    tags=[tags.ITEMS],
    responses=responses.ERROR_RESPONSES,
)
async def get_item_details(
    request: Request,
    potto: PottoDependency,
    user: UserDependency,
    collection_id: CollectionIdPath,
    item_id: ItemIdPath,
    crs: Annotated[
        str | None, Query(description="CRS URI for the response geometry coordinates.")
    ] = None,
):
    """Get details about a collection item."""
    current_locale = babel.Locale.parse(request.state.language)
    collection_item = await potto.api_get_collection_item(
        user,
        collection_id=collection_id,
        item_id=item_id,
        locale=current_locale,
        crs=crs,
    )
    result = GeoJsonItem.from_potto(collection_item, request.url_for)
    response_headers: dict[str, str] = {
        "Content-Type": constants.MEDIA_TYPE_GEO_JSON,
        "Link": ",".join((li.serialize_as_http_header() for li in result.links)),
    }
    if crs_header := (
        collection_item.metadata.get("Content-Crs")
        if collection_item.metadata
        else None
    ):
        response_headers["Content-Crs"] = crs_header
    return JSONResponse(
        result.model_dump(exclude_none=True, by_alias=True),
        headers=response_headers,
    )
