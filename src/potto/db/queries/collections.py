import logging
from typing import cast

import shapely
from sqlalchemy.orm import (
    QueryableAttribute,
    selectinload,
)
from sqlmodel import (
    func,
    or_,
    select,
)
from sqlmodel.ext.asyncio.session import AsyncSession

from ..models import (
    Collection,
    CollectionType,
    User,
)
from .common import _get_total_num_records

logger = logging.getLogger(__name__)


async def collect_all_public_collections(
    session: AsyncSession,
    collection_type_filter: list[CollectionType] | None = None,
) -> list[Collection]:
    _, num_total = await list_public_collections(
        session,
        limit=1,
        collection_type_filter=collection_type_filter,
        include_total=True,
    )
    assert num_total is not None
    items, _ = await list_public_collections(
        session,
        limit=num_total,
        collection_type_filter=collection_type_filter,
        include_total=False,
    )
    return items


async def collect_all_user_collections(
    session: AsyncSession,
    user_id: str | None = None,
    accessible_identifiers: list[str] | None = None,
    collection_type_filter: list[CollectionType] | None = None,
) -> list[Collection]:
    _, num_total = await list_user_collections(
        session,
        limit=1,
        user_id=user_id,
        accessible_identifiers=accessible_identifiers,
        collection_type_filter=collection_type_filter,
        include_total=True,
    )
    assert num_total is not None
    items, _ = await list_user_collections(
        session,
        limit=num_total,
        user_id=user_id,
        accessible_identifiers=accessible_identifiers,
        collection_type_filter=collection_type_filter,
        include_total=False,
    )
    return items


async def paginated_list_public_collections(
    session: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    include_total: bool = False,
    identifier_filter: str | None = None,
    collection_type_filter: list[CollectionType] | None = None,
    spatial_intersect: shapely.Polygon | None = None,
) -> tuple[list[Collection], int | None]:
    limit = page_size
    offset = limit * (page - 1)
    return await list_public_collections(
        session,
        limit=limit,
        offset=offset,
        include_total=include_total,
        identifier_filter=identifier_filter,
        collection_type_filter=collection_type_filter,
        spatial_intersect=spatial_intersect,
    )


async def paginated_list_user_collections(
    session: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    include_total: bool = False,
    user_id: str | None = None,
    accessible_identifiers: list[str] | None = None,
    identifier_filter: str | None = None,
    collection_type_filter: list[CollectionType] | None = None,
    spatial_intersect: shapely.Polygon | None = None,
) -> tuple[list[Collection], int | None]:
    limit = page_size
    offset = limit * (page - 1)
    return await list_user_collections(
        session,
        limit=limit,
        offset=offset,
        include_total=include_total,
        user_id=user_id,
        accessible_identifiers=accessible_identifiers,
        identifier_filter=identifier_filter,
        collection_type_filter=collection_type_filter,
        spatial_intersect=spatial_intersect,
    )


async def list_public_collections(
    session: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
    include_total: bool = False,
    identifier_filter: str | None = None,
    collection_type_filter: list[CollectionType] | None = None,
    spatial_intersect: shapely.Polygon | None = None,
) -> tuple[list[Collection], int | None]:
    logger.debug(f"{locals()=}")
    statement = (
        select(Collection)
        .options(selectinload(cast(QueryableAttribute, Collection.owner)))
        .where(Collection.is_public)
    )
    statement = _apply_common_filters(
        statement, identifier_filter, collection_type_filter, spatial_intersect
    )
    statement = statement.order_by(
        Collection.created_at,
        Collection.resource_identifier.desc().nullslast(),  # ty: ignore[unresolved-attribute]
    )
    items = (await session.exec(statement.offset(offset).limit(limit))).all()
    num_total = (
        await _get_total_num_records(session, statement) if include_total else None
    )
    return items, num_total


async def list_user_collections(
    session: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
    include_total: bool = False,
    user_id: str | None = None,
    accessible_identifiers: list[str] | None = None,
    identifier_filter: str | None = None,
    collection_type_filter: list[CollectionType] | None = None,
    spatial_intersect: shapely.Polygon | None = None,
) -> tuple[list[Collection], int | None]:
    """List collections visible to an authenticated user.

    - accessible_identifiers=None: admin mode, all collections are returned.
    - accessible_identifiers=[...]: returns public collections, collections owned
      by user_id, and collections whose identifier is in accessible_identifiers.
    """
    logger.debug(f"{locals()=}")
    statement = select(Collection).options(
        selectinload(cast(QueryableAttribute, Collection.owner))
    )
    if accessible_identifiers is not None:
        statement = statement.where(
            or_(
                Collection.is_public,
                Collection.owner_id == user_id,
                Collection.resource_identifier.in_(accessible_identifiers),  # ty: ignore[unresolved-attribute]
            )
        )
    statement = _apply_common_filters(
        statement, identifier_filter, collection_type_filter, spatial_intersect
    )
    statement = statement.order_by(
        Collection.created_at,
        Collection.resource_identifier.desc().nullslast(),  # ty: ignore[unresolved-attribute]
    )
    items = (await session.exec(statement.offset(offset).limit(limit))).all()
    num_total = (
        await _get_total_num_records(session, statement) if include_total else None
    )
    return items, num_total


def _apply_common_filters(
    statement, identifier_filter, collection_type_filter, spatial_intersect
):
    if identifier_filter:
        statement = statement.where(
            Collection.resource_identifier.ilike(f"%{identifier_filter}%")  # ty: ignore[unresolved-attribute]
        )
    if collection_type_filter:
        statement = statement.where(
            Collection.collection_type in collection_type_filter
        )
    if spatial_intersect is not None:
        statement = statement.where(
            or_(
                func.ST_Intersects(
                    Collection.spatial_extent,
                    func.ST_GeomFromText(spatial_intersect.wkt, 4326),
                ),
                Collection.spatial_extent.is_(None),  # ty: ignore[unresolved-attribute]
            )
        )
    return statement


async def get_collection(
    session: AsyncSession,
    collection_id: int,
) -> Collection | None:
    statement = (
        select(Collection)
        .options(selectinload(cast(QueryableAttribute, Collection.owner)))
        .where(Collection.id == collection_id)
    )
    return (await session.exec(statement)).first()


async def get_collection_editors(
    session: AsyncSession,
    resource_identifier: str,
) -> list[User]:
    statement = select(User).where(
        User.scopes.contains([f"collection-{resource_identifier}:editor"])  # ty: ignore[unresolved-attribute]
    )
    return list((await session.exec(statement)).all())


async def get_collection_viewers(
    session: AsyncSession,
    resource_identifier: str,
) -> list[User]:
    statement = select(User).where(
        User.scopes.contains([f"collection-{resource_identifier}:viewer"])  # ty: ignore[unresolved-attribute]
    )
    return list((await session.exec(statement)).all())


async def get_collection_by_resource_identifier(
    session: AsyncSession,
    resource_identifier: str,
) -> Collection | None:
    statement = (
        select(Collection)
        .options(selectinload(cast(QueryableAttribute, Collection.owner)))
        .where(Collection.resource_identifier == resource_identifier)
    )
    return (await session.exec(statement)).first()


async def get_owned_collection_identifiers(
    session: AsyncSession,
    user_id: str,
) -> list[str]:
    statement = select(Collection.resource_identifier).where(
        Collection.owner_id == user_id
    )
    return list((await session.exec(statement)).all())
