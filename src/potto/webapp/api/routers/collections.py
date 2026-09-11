import copy
import logging

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    Response,
)
from fastapi.responses import JSONResponse

from ....constants import (
    LinkRelation,
    MediaType,
)
from ....exceptions import PottoException
from ....schemas.collections import CollectionManagerCapabilities
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
    collections = await potto.list_collections(user=user, page_size=limit)
    result = JsonCollectionList.from_potto(collections, request.url_for)
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
    if (collection := await potto.get_collection(collection_id, user=user)) is None:
        raise HTTPException(status_code=404, detail="Collection not found.")
    result = JsonCollection.from_potto(collection, request.url_for)
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
    locale: LocaleDependency,
) -> JSONResponse:
    """
    Get a list of properties that can be used to query a collection's contents.
    """
    if (
        collection := await potto.get_collection(
            collection_id,
            user=user,
            include_queryables=True,
        )
    ) is None:
        raise HTTPException(status_code=404, detail="Collection not found.")
    assert collection.queryables is not None
    queryables = copy.deepcopy(collection.queryables)
    queryables["$id"] = str(
        request.url_for("api:collection-get", collection_id=collection_id)
    )
    links = [
        base_schemas.Link(
            type=MediaType.JSON,
            rel=LinkRelation.HOME,
            href=str(request.url_for("api:landing-page")),
        ),
        base_schemas.Link(
            type=MediaType.JSON,
            rel=LinkRelation.COLLECTION,
            href=str(
                request.url_for("api:collection-get", collection_id=collection_id)
            ),
        ),
    ]
    return JSONResponse(
        headers={
            "Content-Type": MediaType.JSON_SCHEMA,
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
    locale: LocaleDependency,
) -> JSONResponse:
    """Get the schema of a collection."""

    if (
        collection := await potto.get_collection(
            collection_id,
            user=user,
            include_schema=True,
        )
    ) is None:
        raise HTTPException(
            status_code=404, detail=f"Collection {collection_id} not found"
        )

    assert collection.schema is not None
    schema = copy.deepcopy(collection.schema)
    schema["$id"] = str(
        request.url_for("api:collection-get", collection_id=collection_id)
    )
    links = [
        base_schemas.Link(
            type=MediaType.JSON,
            rel=LinkRelation.HOME,
            href=str(request.url_for("api:landing-page")),
        ),
        base_schemas.Link(
            type=MediaType.JSON,
            rel=LinkRelation.COLLECTION,
            href=str(
                request.url_for("api:collection-get", collection_id=collection_id)
            ),
        ),
    ]
    return JSONResponse(
        headers={
            "Content-Type": MediaType.JSON_SCHEMA,
            "Link": ",".join((li.serialize_as_http_header() for li in links)),
        },
        content=schema,
    )


async def create_collection(
    request: Request,
    to_create: collections_schemas.CollectionCreate,
    settings: SettingsDependency,
    user: UserDependency,
):
    """Create a new collection."""
    if user is None:
        raise HTTPException(status_code=404, detail="An authenticated user is required")
    collection = await settings.get_collection_manager().create_collection(
        to_create, user
    )
    return JsonCollection.from_potto(collection, request.url_for)


async def delete_collection(
    collection_id: CollectionIdPath,
    user: UserDependency,
    settings: SettingsDependency,
):
    """Delete collection."""
    if user is None:
        raise HTTPException(status_code=404, detail="An authenticated user is required")
    collection_manager = settings.get_collection_manager()
    collection = await collection_manager.get_collection(collection_id, user)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    await collection_manager.delete_collection(collection_id, user)


async def grant_collection_access(
    collection_id: CollectionIdPath,
    user_id: UserIdPath,
    body: collections_schemas.CollectionAccessGrant,
    user: UserDependency,
    settings: SettingsDependency,
):
    """Grant access to a private collection.

    Grant either `viewer` or `editor` roles on a private collection to the
    input `user_id`. This operation can only be called by the collection
    owner.
    """
    if user is None:
        raise HTTPException(status_code=404, detail="An authenticated user is required")
    collection_manager = settings.get_collection_manager()
    collection = await collection_manager.get_collection(collection_id, user)
    if collection is None:
        raise PottoException(f"Collection {collection_id!r} not found.")
    await collection_manager.grant_collection_access(
        granting_user=user,
        target_user_id=user_id,
        collection=collection,
        role=body.role,
    )


async def revoke_collection_access(
    collection_id: CollectionIdPath,
    user_id: UserIdPath,
    user: UserDependency,
    settings: SettingsDependency,
):
    """Revoke access to a collection.

    Revoke access to a private collection by the user with the input `user_id`.
    This operation can only be called by the collection owner.
    """
    if user is None:
        raise HTTPException(status_code=404, detail="An authenticated user is required")
    collection_manager = settings.get_collection_manager()
    collection = await collection_manager.get_collection(collection_id, user)
    if collection is None:
        raise PottoException(f"Collection {collection_id!r} not found.")
    await collection_manager.revoke_collection_access(
        revoking_user=user,
        target_user_id=user_id,
        collection=collection,
    )


def register_mutating_routes(
    target_router: APIRouter, capabilities: CollectionManagerCapabilities
) -> None:
    """Attach collection-mutating routes to `target_router`, per manager capabilities.

    Kept separate from the module-level `router` (which only ever holds the always-available
    read routes) so each FastAPI app build can decide independently which mutating routes to
    include, without permanently mutating a module-level singleton shared across app builds.
    """
    if capabilities.supports_creation:
        target_router.post(
            "/collections",
            name="create-collection",
            response_model=JsonCollection,
            tags=[tags.COLLECTIONS],
            responses=responses.ERROR_RESPONSES,
        )(create_collection)
    if capabilities.supports_deletion:
        target_router.delete(
            "/collections/{collection_id}",
            name="delete-collection",
            tags=[tags.COLLECTIONS],
            responses=responses.ERROR_RESPONSES,
        )(delete_collection)
    if capabilities.supports_granting_access:
        target_router.put(
            "/collections/{collection_id}/access/{user_id}",
            name="grant-collection-access",
            status_code=204,
            tags=[tags.COLLECTIONS],
            responses=responses.ERROR_RESPONSES,
        )(grant_collection_access)
    if capabilities.supports_revoking_access:
        target_router.delete(
            "/collections/{collection_id}/access/{user_id}",
            name="revoke-collection-access",
            status_code=204,
            tags=[tags.COLLECTIONS],
            responses=responses.ERROR_RESPONSES,
        )(revoke_collection_access)
