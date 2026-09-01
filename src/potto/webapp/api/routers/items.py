import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
    Response,
)

from ....schemas.features import PottoFeatureFilter
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
    response_model=GeoJsonItemCollection,
    response_model_by_alias=True,
    response_model_exclude_none=True,
    response_class=responses.GeoJsonResponse,
)
async def list_collection_items(
    request: Request,
    response: Response,
    collection_id: CollectionIdPath,
    filter_: Annotated[PottoFeatureFilter, Query()],
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
        collection_items = await potto.list_collection_items(
            collection_id, user=user, filter_=filter_, session=session
        )
    result = GeoJsonItemCollection.from_potto(collection_items, request.url_for)
    response.headers.update(
        {
            "Link": ",".join((li.serialize_as_http_header() for li in result.links)),
            "Content-Crs": (
                f"<{[i.crs for i in collection_items.features][0]}>"
                if len(collection_items.features) > 0
                else collection_items.storage_crs
            ),
            **(
                {str(k): str(v) for k, v in collection_items.metadata}
                if collection_items.metadata
                else {}
            ),
        }
    )
    return result


@router.get(
    "/collections/{collection_id}/items/{item_id}",
    name="collection-item-get",
    tags=[tags.ITEMS],
    responses=responses.ERROR_RESPONSES,
    response_model=GeoJsonItem,
    response_model_by_alias=True,
    response_model_exclude_none=True,
    response_class=responses.GeoJsonResponse,
)
async def get_item_details(
    request: Request,
    response: Response,
    potto: PottoDependency,
    user: UserDependency,
    settings: SettingsDependency,
    collection_id: CollectionIdPath,
    item_id: ItemIdPath,
    crs: Annotated[
        str | None, Query(description="CRS URI for the response geometry coordinates.")
    ] = None,
):
    """Get details about a collection item."""
    async with settings.get_db_session_maker()() as session:
        collection_item = await potto.get_collection_item(
            user,
            collection_id=collection_id,
            item_id=item_id,
            crs=crs,
            session=session,
        )
    result = GeoJsonItem.from_potto(collection_item, request.url_for)
    response.headers.update(
        {
            "Link": ",".join((li.serialize_as_http_header() for li in result.links)),
            "Content-Crs": f"<{collection_item.feature.crs}>",
            **(
                {str(k): str(v) for k, v in collection_item.metadata}
                if collection_item.metadata
                else {}
            ),
        }
    )
    return result
