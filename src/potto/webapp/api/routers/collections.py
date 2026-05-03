import copy
import logging

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
)
from fastapi.responses import JSONResponse

from .... import constants
from ....exceptions import PottoException
from ....operations import collections as collection_operations
from ....schemas import (
    base as base_schemas,
    collections as collections_schemas,
)
from ....schemas.web.collections import (
    JsonCollectionList,
    JsonCollection,
)
from ..dependencies import (
    AuthorizationBackendDependency,
    LocaleDependency,
    PaginationLimitDependency,
    PottoDependency,
    SettingsDependency,
    UserDependency,
)


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/collections",
    name="collection-list",
    response_model_exclude_none=True,
    response_model=JsonCollectionList,
    tags=["collections"],
)
async def list_collections(
    request: Request,
    potto: PottoDependency,
    user: UserDependency,
    locale: LocaleDependency,
    limit: PaginationLimitDependency,
) -> JSONResponse:
    potto_collections = await potto.api_list_collections(
        user=user, locale=locale, page_size=limit
    )
    result = JsonCollectionList.from_potto(potto_collections, request.url_for)
    return JSONResponse(
        result.model_dump(exclude_none=True, by_alias=True),
        headers={
            "Link": ",".join((li.serialize_as_http_header() for li in result.links))
        },
    )


@router.get(
    "/collections/{collection_id}",
    name="collection-get",
    response_model=JsonCollection,
    tags=["collections"],
)
async def get_collection_details(
    request: Request,
    collection_id: str,
    potto: PottoDependency,
    user: UserDependency,
    locale: LocaleDependency,
):
    if (
        potto_collection := await potto.api_get_collection(
            collection_id, user=user, locale=locale
        )
    ) is None:
        raise HTTPException(status_code=404, detail="Collection not found.")
    result = JsonCollection.from_potto(potto_collection, request.url_for)
    return JSONResponse(
        result.model_dump(exclude_none=True, by_alias=True),
        headers={
            "Link": ",".join((li.serialize_as_http_header() for li in result.links))
        },
    )


@router.get(
    "/collections/{collection_id}/queryables",
    name="collection-get-queryables",
    tags=["collections"],
)
async def get_collection_queryables(
    request: Request,
    collection_id: str,
    potto: PottoDependency,
    user: UserDependency,
    locale: LocaleDependency,
) -> JSONResponse:
    potto_collection = await potto.api_get_collection(
        collection_id, user=user, locale=locale, include_queryables=True
    )
    if potto_collection is None:
        raise HTTPException(status_code=404, detail="Collection not found.")
    assert potto_collection.queryables is not None
    queryables = copy.deepcopy(potto_collection.queryables)
    queryables["$id"] = str(
        request.url_for("api:collection-get", collection_id=collection_id)
    )
    links = [
        base_schemas.Link(
            type=constants.MEDIA_TYPE_JSON,
            rel=constants.REL_HOME,
            href=str(request.url_for("api:landing-page")),
        ),
        base_schemas.Link(
            type=constants.MEDIA_TYPE_JSON,
            rel=constants.REL_COLLECTION,
            href=str(
                request.url_for("api:collection-get", collection_id=collection_id)
            ),
        ),
    ]
    return JSONResponse(
        headers={
            "Content-Type": constants.MEDIA_TYPE_JSON_SCHEMA,
            "Link": ",".join((li.serialize_as_http_header() for li in links)),
        },
        content=queryables,
    )


@router.get(
    "/collections/{collection_id}/schema",
    name="collection-get-schema",
    tags=["collections"],
)
async def get_collection_schema(
    request: Request,
    collection_id: str,
    potto: PottoDependency,
    user: UserDependency,
    locale: LocaleDependency,
) -> JSONResponse:
    potto_collection = await potto.api_get_collection(
        collection_id, user=user, locale=locale, include_schema=True
    )
    if potto_collection is None:
        raise HTTPException(
            status_code=404, detail=f"Collection {collection_id} not found"
        )

    assert potto_collection.schema is not None
    schema = copy.deepcopy(potto_collection.schema)
    schema["$id"] = str(
        request.url_for("api:collection-get", collection_id=collection_id)
    )
    links = [
        base_schemas.Link(
            type=constants.MEDIA_TYPE_JSON,
            rel=constants.REL_HOME,
            href=str(request.url_for("api:landing-page")),
        ),
        base_schemas.Link(
            type=constants.MEDIA_TYPE_JSON,
            rel=constants.REL_COLLECTION,
            href=str(
                request.url_for("api:collection-get", collection_id=collection_id)
            ),
        ),
    ]
    return JSONResponse(
        headers={
            "Content-Type": constants.MEDIA_TYPE_JSON_SCHEMA,
            "Link": ",".join((li.serialize_as_http_header() for li in links)),
        },
        content=schema,
    )


@router.post(
    "/collections",
    name="create-collection",
    response_model=JsonCollection,
    tags=["collections"],
)
async def create_collection(
    request: Request,
    to_create: collections_schemas.CollectionCreate,
    settings: SettingsDependency,
    user: UserDependency,
    authorization_backend: AuthorizationBackendDependency,
):
    async with settings.get_db_session_maker()() as session:
        db_collection = await collection_operations.create_collection(
            session, user, authorization_backend, to_create
        )
    return JsonCollection.from_db_item(db_collection, request.url_for)


@router.delete(
    "/collections/{collection_id}",
    name="delete-collection",
    tags=["collections"],
)
async def delete_collection(
    collection_id: str,
    user: UserDependency,
    authorization_backend: AuthorizationBackendDependency,
    settings: SettingsDependency,
):
    if user is None:
        raise HTTPException(status_code=404, detail="An authenticated user is required")
    async with settings.get_db_session_maker()() as session:
        await collection_operations.delete_collection(
            session, user, authorization_backend, int(collection_id)
        )


@router.put(
    "/collections/{collection_id}/access/{user_id}",
    name="grant-collection-access",
    status_code=204,
    tags=["collections"],
)
async def grant_collection_access(
    collection_id: str,
    user_id: str,
    body: collections_schemas.CollectionAccessGrant,
    user: UserDependency,
    authorization_backend: AuthorizationBackendDependency,
    settings: SettingsDependency,
):
    if user is None:
        raise HTTPException(status_code=404, detail="An authenticated user is required")
    async with settings.get_db_session_maker()() as session:
        collection = await collection_operations.get_collection_by_resource_identifier(
            session, user, authorization_backend, collection_id
        )
        if collection is None:
            raise PottoException(f"Collection {collection_id!r} not found.")
        await collection_operations.grant_collection_access(
            session, user, authorization_backend, user_id, collection, body.role
        )


@router.delete(
    "/collections/{collection_id}/access/{user_id}",
    name="revoke-collection-access",
    status_code=204,
    tags=["collections"],
)
async def revoke_collection_access(
    collection_id: str,
    user_id: str,
    user: UserDependency,
    authorization_backend: AuthorizationBackendDependency,
    settings: SettingsDependency,
):
    if user is None:
        raise HTTPException(status_code=404, detail="An authenticated user is required")
    async with settings.get_db_session_maker()() as session:
        collection = await collection_operations.get_collection_by_resource_identifier(
            session, user, authorization_backend, collection_id
        )
        if collection is None:
            raise PottoException(f"Collection {collection_id!r} not found.")
        await collection_operations.revoke_collection_access(
            session, user, authorization_backend, user_id, collection
        )
