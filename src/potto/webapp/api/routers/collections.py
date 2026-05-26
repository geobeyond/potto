import copy
import logging

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    Response,
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
from .. import (
    responses,
    tags,
)
from ..dependencies import (
    AuthorizationBackendDependency,
    CollectionIdPath,
    LocaleDependency,
    PaginationLimitDependency,
    PottoDependency,
    SettingsDependency,
    UserDependency,
    UserIdPath,
)


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/collections",
    name="collection-list",
    tags=[tags.COLLECTIONS],
    responses=responses.ERROR_RESPONSES,
    response_model=JsonCollectionList,
    response_model_exclude_none=True,
    response_model_by_alias=True,
)
async def list_collections(
    request: Request,
    response: Response,
    potto: PottoDependency,
    user: UserDependency,
    settings: SettingsDependency,
    locale: LocaleDependency,
    limit: PaginationLimitDependency,
):
    """List collections available on this server.

    Collection visibility is subject to the requesting user's access levels:

    - Public collections are visible to all users and do not require
      authentication;
    - Private collections are visible to their owner and to any users that
      have the 'collection-{collection_identifier}:{editor|viewer}' scope
    """
    async with settings.get_db_session_maker()() as session:
        potto_collections = await potto.list_collections(
            user=user, page_size=limit, session=session
        )
    result = JsonCollectionList.from_potto(potto_collections, request.url_for)
    response.headers.update(
        {"Link": ",".join((li.serialize_as_http_header() for li in result.links))}
    )
    return result


@router.get(
    "/collections/{collection_id}",
    name="collection-get",
    tags=[tags.COLLECTIONS],
    responses=responses.ERROR_RESPONSES,
    response_model=JsonCollection,
    response_model_exclude_none=True,
    response_model_by_alias=True,
)
async def get_collection_details(
    request: Request,
    response: Response,
    collection_id: CollectionIdPath,
    potto: PottoDependency,
    user: UserDependency,
    locale: LocaleDependency,
    settings: SettingsDependency,
):
    """Get details about a collection.

    Access to the collection is subject to the requesting user's access level:

    - Public collections are visible to all users and do not require
      authentication
    - Private collections are visible to their owner and to any users that
      have the 'collection-{collection_identifier}:{editor|viewer}' scope
    """
    async with settings.get_db_session_maker()() as session:
        if (
            potto_collection := await potto.get_collection(
                collection_id, user=user, session=session
            )
        ) is None:
            raise HTTPException(status_code=404, detail="Collection not found.")
    result = JsonCollection.from_potto(potto_collection, request.url_for)
    response.headers.update(
        {"Link": ",".join((li.serialize_as_http_header() for li in result.links))}
    )
    return result


@router.get(
    "/collections/{collection_id}/queryables",
    name="collection-get-queryables",
    tags=[tags.COLLECTIONS],
    responses=responses.ERROR_RESPONSES,
)
async def get_collection_queryables(
    request: Request,
    collection_id: CollectionIdPath,
    potto: PottoDependency,
    user: UserDependency,
    settings: SettingsDependency,
    locale: LocaleDependency,
) -> JSONResponse:
    """
    Get a list of properties that can be used to query a collection's contents.
    """
    async with settings.get_db_session_maker()() as session:
        potto_collection = await potto.get_collection(
            collection_id,
            user=user,
            include_queryables=True,
            session=session,
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
    tags=[tags.COLLECTIONS],
    responses=responses.ERROR_RESPONSES,
)
async def get_collection_schema(
    request: Request,
    collection_id: CollectionIdPath,
    potto: PottoDependency,
    user: UserDependency,
    settings: SettingsDependency,
    locale: LocaleDependency,
) -> JSONResponse:
    """Get the schema of a collection."""
    async with settings.get_db_session_maker()() as session:
        potto_collection = await potto.get_collection(
            collection_id,
            user=user,
            include_schema=True,
            session=session,
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
    tags=[tags.COLLECTIONS],
    responses=responses.ERROR_RESPONSES,
)
async def create_collection(
    request: Request,
    to_create: collections_schemas.CollectionCreate,
    settings: SettingsDependency,
    user: UserDependency,
    authorization_backend: AuthorizationBackendDependency,
):
    """Create a new collection."""
    async with settings.get_db_session_maker()() as session:
        db_collection = await collection_operations.create_collection(
            session, user, authorization_backend, to_create
        )
    return JsonCollection.from_db_item(db_collection, request.url_for)


@router.delete(
    "/collections/{collection_id}",
    name="delete-collection",
    tags=[tags.COLLECTIONS],
    responses=responses.ERROR_RESPONSES,
)
async def delete_collection(
    collection_id: CollectionIdPath,
    user: UserDependency,
    authorization_backend: AuthorizationBackendDependency,
    settings: SettingsDependency,
):
    """Delete collection."""
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
    tags=[tags.COLLECTIONS],
    responses=responses.ERROR_RESPONSES,
)
async def grant_collection_access(
    collection_id: CollectionIdPath,
    user_id: UserIdPath,
    body: collections_schemas.CollectionAccessGrant,
    user: UserDependency,
    authorization_backend: AuthorizationBackendDependency,
    settings: SettingsDependency,
):
    """Grant access to a private collection.

    Grant either `viewer` or `editor` roles on a private collection to the
    input `user_id`. This operation can only be called by the collection
    owner.
    """
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
    tags=[tags.COLLECTIONS],
    responses=responses.ERROR_RESPONSES,
)
async def revoke_collection_access(
    collection_id: CollectionIdPath,
    user_id: UserIdPath,
    user: UserDependency,
    authorization_backend: AuthorizationBackendDependency,
    settings: SettingsDependency,
):
    """Revoke access to a collection.

    Revoke access to a private collection by the user with the input `user_id`.
    This operation can only be called by the collection owner.
    """
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
