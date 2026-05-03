import logging
from typing import Annotated

import babel
from fastapi import (
    APIRouter,
    Query,
    Request,
)
from fastapi.responses import JSONResponse

from .... import constants
from ....schemas.base import (
    ItemFilter,
    FeatureFilter,
)
from ....schemas.web.items import (
    GeoJsonItem,
    GeoJsonItemCollection,
)
from ..dependencies import (
    LocaleDependency,
    PottoDependency,
    UserDependency,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/collections/{collection_id}/items",
    name="collection-item-list",
    tags=["items"],
)
async def list_collection_items(
    request: Request,
    collection_id: str,
    filter_: Annotated[ItemFilter, Query()],
    potto: PottoDependency,
    user: UserDependency,
    locale: LocaleDependency,
):
    collection_items = await potto.api_list_collection_items(
        collection_id,
        user=user,
        locale=locale,
        filter_=FeatureFilter.model_validate(
            filter_.model_dump(by_alias=True, exclude_none=True)
        ),
    )
    result = GeoJsonItemCollection.from_potto(collection_items, request.url_for)
    return JSONResponse(
        result.model_dump(exclude_none=True, by_alias=True),
        headers={
            "Content-Type": constants.MEDIA_TYPE_GEO_JSON,
            "Link": ",".join((li.serialize_as_http_header() for li in result.links)),
        },
    )


@router.get(
    "/collections/{collection_id}/items/{item_id}",
    name="collection-item-get",
    tags=["items"],
)
async def get_item_details(
    request: Request,
    potto: PottoDependency,
    user: UserDependency,
    collection_id: str,
    item_id: str,
):
    current_locale = babel.Locale.parse(request.state.language)
    collection_item = await potto.api_get_collection_item(
        user,
        collection_id=collection_id,
        item_id=item_id,
        locale=current_locale,
    )
    result = GeoJsonItem.from_potto(collection_item, request.url_for)
    return JSONResponse(
        result.model_dump(exclude_none=True, by_alias=True),
        headers={
            "Content-Type": constants.MEDIA_TYPE_GEO_JSON,
            "Link": ",".join((li.serialize_as_http_header() for li in result.links)),
        },
    )
