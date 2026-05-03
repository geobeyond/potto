import copy
import logging

import shapely
from sqlmodel.ext.asyncio.session import AsyncSession

from .. import (
    constants,
    util,
)
from ..authz.base import AuthorizationBackendProtocol
from ..db.models import Collection
from ..db.commands import (
    auth as auth_commands,
    collections as collection_commands,
)
from ..db.queries import (
    auth as auth_queries,
    collections as collection_queries,
)
from ..exceptions import (
    PottoCannotChangeCollectionOwnerException,
    PottoCannotCreateCollectionException,
    PottoCannotDeleteCollectionException,
    PottoCannotEditCollectionException,
    PottoException,
)
from ..schemas.auth import PottoScope, PottoUser
from ..schemas.base import (
    CollectionProvider,
    CollectionProviderConfiguration,
    CollectionType,
)
from ..schemas.auth import UserUpdate
from ..schemas.collections import (
    CollectionCreate,
    CollectionUpdate,
)

logger = logging.getLogger(__name__)


async def collect_all_collections(
    session: AsyncSession,
    user: PottoUser | None,
    authorization_backend: AuthorizationBackendProtocol,
    collection_type_filter: list[CollectionType] | None = None,
) -> list[Collection]:
    """List all collections that the user has access to."""
    if user is None:
        return await collection_queries.collect_all_public_collections(
            session,
            collection_type_filter=collection_type_filter,
        )
    accessible_ids = await authorization_backend.get_accessible_collection_identifiers(
        user
    )
    return await collection_queries.collect_all_user_collections(
        session,
        user_id=user.id,
        accessible_identifiers=accessible_ids,
        collection_type_filter=collection_type_filter,
    )


async def paginated_list_collections(
    session: AsyncSession,
    user: PottoUser | None,
    authorization_backend: AuthorizationBackendProtocol,
    *,
    page: int = 1,
    page_size: int = 20,
    include_total: bool = False,
    identifier_filter: str | None = None,
    collection_type_filter: list[CollectionType] | None = None,
    spatial_intersect: shapely.Polygon | None = None,
) -> tuple[list[Collection], int | None]:
    """Produce a paginated list of all collections that the user has access to."""
    if user is None:
        return await collection_queries.paginated_list_public_collections(
            session,
            page=page,
            page_size=page_size,
            include_total=include_total,
            identifier_filter=identifier_filter,
            collection_type_filter=collection_type_filter,
            spatial_intersect=spatial_intersect,
        )
    accessible_ids = await authorization_backend.get_accessible_collection_identifiers(
        user
    )
    return await collection_queries.paginated_list_user_collections(
        session,
        page=page,
        page_size=page_size,
        include_total=include_total,
        identifier_filter=identifier_filter,
        user_id=user.id,
        accessible_identifiers=accessible_ids,
        collection_type_filter=collection_type_filter,
        spatial_intersect=spatial_intersect,
    )


async def get_collection(
    session: AsyncSession,
    user: PottoUser | None,
    authorization_backend: AuthorizationBackendProtocol,
    collection_id: int,
) -> Collection | None:
    collection = await collection_queries.get_collection(session, collection_id)
    if collection is None:
        return None
    if not await authorization_backend.can_view_collection(user, collection):
        return None
    return collection


async def get_collection_by_resource_identifier(
    session: AsyncSession,
    user: PottoUser | None,
    authorization_backend: AuthorizationBackendProtocol,
    identifier: str,
) -> Collection | None:
    collection = await collection_queries.get_collection_by_resource_identifier(
        session, identifier
    )
    if collection is None:
        return None
    if not await authorization_backend.can_view_collection(user, collection):
        return None
    return collection


async def create_collection(
    session: AsyncSession,
    user: PottoUser | None,
    authorization_backend: AuthorizationBackendProtocol,
    to_create: CollectionCreate,
) -> Collection:
    if not await authorization_backend.can_create_collection(user):
        raise PottoCannotCreateCollectionException(
            "User does not have permission to create a collection."
        )
    return await collection_commands.create_collection(session, to_create)


async def update_collection(
    session: AsyncSession,
    user: PottoUser | None,
    authorization_backend: AuthorizationBackendProtocol,
    collection: Collection,
    to_update: CollectionUpdate,
) -> Collection:
    if not await authorization_backend.can_edit_collection(user, collection):
        raise PottoCannotEditCollectionException(
            f"User does not have permission to edit collection "
            f"{collection.resource_identifier!r}."
        )
    if to_update.owner_id is not None and to_update.owner_id != collection.owner_id:
        if not await authorization_backend.can_change_collection_owner(
            user, collection
        ):
            raise PottoCannotChangeCollectionOwnerException(
                f"User does not have permission to change the owner of collection "
                f"{collection.resource_identifier!r}."
            )
    return await collection_commands.update_collection(session, collection, to_update)


async def delete_collection(
    session: AsyncSession,
    user: PottoUser,
    authorization_backend: AuthorizationBackendProtocol,
    collection_id: int,
) -> None:
    collection = await collection_queries.get_collection(session, collection_id)
    if collection is None:
        raise PottoException(f"Collection with id {collection_id} does not exist.")
    if not await authorization_backend.can_edit_collection(user, collection):
        raise PottoCannotDeleteCollectionException(
            f"User does not have permission to delete collection {collection_id}."
        )
    return await collection_commands.delete_collection(session, collection_id)


async def grant_collection_access(
    session: AsyncSession,
    granting_user: PottoUser,
    authorization_backend: AuthorizationBackendProtocol,
    target_user_id: str,
    collection: Collection,
    role: str,
) -> None:
    if not await authorization_backend.can_edit_collection(granting_user, collection):
        raise PottoException(
            "User does not have permission to grant access to this collection."
        )
    target_user = await auth_queries.get_user(session, target_user_id)
    if target_user is None:
        raise PottoException(f"User with id {target_user_id!r} does not exist.")
    editor_scope = PottoScope.collection_editor(collection.resource_identifier)
    viewer_scope = PottoScope.collection_viewer(collection.resource_identifier)
    new_scopes = [
        s for s in target_user.scopes if s not in (editor_scope, viewer_scope)
    ]
    if role == "editor":
        new_scopes.append(editor_scope)
    else:
        new_scopes.append(viewer_scope)
    await auth_commands.update_user(session, target_user, UserUpdate(scopes=new_scopes))


async def revoke_collection_access(
    session: AsyncSession,
    revoking_user: PottoUser,
    authorization_backend: AuthorizationBackendProtocol,
    target_user_id: str,
    collection: Collection,
) -> None:
    if not await authorization_backend.can_edit_collection(revoking_user, collection):
        raise PottoException(
            "User does not have permission to revoke access to this collection."
        )
    target_user = await auth_queries.get_user(session, target_user_id)
    if target_user is None:
        raise PottoException(f"User with id {target_user_id!r} does not exist.")
    editor_scope = PottoScope.collection_editor(collection.resource_identifier)
    viewer_scope = PottoScope.collection_viewer(collection.resource_identifier)
    new_scopes = [
        s for s in target_user.scopes if s not in (editor_scope, viewer_scope)
    ]
    await auth_commands.update_user(session, target_user, UserUpdate(scopes=new_scopes))


def _get_crs_info(
    pygeoapi_collection: dict,
) -> tuple[list[str], str | None, str | None]:
    supported_crs = {constants.CRS_84}
    storage_crs = None
    storage_crs_coordinate_epoch = None
    for provider_conf in pygeoapi_collection.get("providers", []):
        if (advertised_crs_list := provider_conf.get("crs")) is not None:
            supported_crs.update(advertised_crs_list)
        if (provider_storage_crs := provider_conf.get("storage_crs")) is not None:
            storage_crs = provider_storage_crs
        if (
            provider_storage_crs_coordinate_epoch := provider_conf.get(
                "storage_crs_coordinate_epoch"
            )
        ) is not None:
            storage_crs_coordinate_epoch = provider_storage_crs_coordinate_epoch
        if all((storage_crs, supported_crs, storage_crs_coordinate_epoch)):
            break
    return list(supported_crs), storage_crs, storage_crs_coordinate_epoch


async def import_pygeoapi_collection(
    session: AsyncSession,
    user: PottoUser,
    authorization_backend: AuthorizationBackendProtocol,
    identifier: str,
    pygeoapi_collection: dict,
    *,
    overwrite: bool = False,
) -> Collection:
    existing_db_collection = (
        await collection_queries.get_collection_by_resource_identifier(
            session, identifier
        )
    )
    if existing_db_collection and not overwrite:
        raise PottoException(f"Collection {identifier!r} already exists!")
    resource_spatial_extents = pygeoapi_collection.get("extents", {}).get("spatial", {})
    spatial_extent = None
    spatial_extent_crs = None
    try:
        if (raw_bbox := resource_spatial_extents.get("bbox")) is not None:
            spatial_extent = shapely.box(*raw_bbox)
            spatial_extent_crs = resource_spatial_extents.get(
                "crs", constants.CRS_84h if spatial_extent.has_z else constants.CRS_84
            )
            # TODO: convert the bbox to either CRS84 or CRS84h, if given something else
    except TypeError:
        logger.exception(
            f"Could not extract bbox from collection {identifier!r}, setting "
            f"spatial_extent to None"
        )
    supported_crs = None
    storage_crs = None
    storage_crs_coordinate_epoch = None
    if spatial_extent is not None:
        supported_crs, storage_crs, storage_crs_coordinate_epoch = _get_crs_info(
            pygeoapi_collection
        )
    providers = {}
    for prov in pygeoapi_collection.get("providers", []):
        modifiable_prov = copy.deepcopy(prov)
        if (type_ := modifiable_prov.pop("type")) in providers.keys():
            continue
        providers[type_] = CollectionProvider(
            python_callable=modifiable_prov.pop("name"),
            config=CollectionProviderConfiguration(
                data=modifiable_prov.pop("data"), options=modifiable_prov
            ),
        )

    collection_type = util.get_collection_type(pygeoapi_collection)
    if existing_db_collection and overwrite:
        if not await authorization_backend.can_edit_collection(
            user, existing_db_collection
        ):
            raise PottoException(
                f"User does not have permission to overwrite collection {identifier!r}."
            )
        logger.debug(f"Updating existing collection {identifier!r}...")
        to_update = CollectionUpdate(
            collection_type=collection_type,
            title=pygeoapi_collection.get("title", ""),
            description=pygeoapi_collection.get("description"),
            keywords=pygeoapi_collection.get("keywords"),
            spatial_extent=spatial_extent,
            spatial_extent_crs=spatial_extent_crs,
            crs=supported_crs,
            storage_crs=storage_crs,
            storage_crs_coordinate_epoch=storage_crs_coordinate_epoch,
            temporal_extent_begin=pygeoapi_collection.get("extents", {})
            .get("temporal", {})
            .get("begin"),
            temporal_extent_end=pygeoapi_collection.get("extents", {})
            .get("temporal", {})
            .get("end"),
            additional_links=pygeoapi_collection.get("links"),
            providers=providers,
        )
        return await collection_commands.update_collection(
            session, existing_db_collection, to_update
        )
    else:
        to_create = CollectionCreate(
            resource_identifier=identifier,
            owner_id=user.id,
            collection_type=collection_type,
            title=pygeoapi_collection.get("title", ""),
            description=pygeoapi_collection.get("description"),
            keywords=pygeoapi_collection.get("keywords"),
            spatial_extent=spatial_extent,
            spatial_extent_crs=spatial_extent_crs,
            crs=supported_crs,
            storage_crs=storage_crs,
            storage_crs_coordinate_epoch=storage_crs_coordinate_epoch,
            temporal_extent_begin=pygeoapi_collection.get("extents", {})
            .get("temporal", {})
            .get("begin"),
            temporal_extent_end=pygeoapi_collection.get("extents", {})
            .get("temporal", {})
            .get("end"),
            additional_links=pygeoapi_collection.get("links"),
            providers=providers,
        )
        return await create_collection(session, user, authorization_backend, to_create)
