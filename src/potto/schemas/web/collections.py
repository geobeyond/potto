import logging
from typing import Annotated

import pydantic

from ... import constants
from ...db import models
from ...webapp.protocols import UrlResolver
from ...webapp.util import get_base_links
from .. import (
    base,
    potto as potto_schemas,
)

logger = logging.getLogger(__name__)


class JsonCollection(pydantic.BaseModel):
    id_: Annotated[str, pydantic.Field(serialization_alias="id")]
    title: base.Title
    description: base.MaybeDescription
    links: list[base.Link]
    extent: base.Extent | None = None
    item_type: Annotated[str | None, pydantic.Field(serialization_alias="itemType")] = (
        constants.FEATURE_COLLECTION_ITEM_TYPE
    )
    crs: list[str] | None = pydantic.Field(default_factory=lambda: [constants.CRS_84])
    storage_crs: Annotated[
        str | None, pydantic.Field(serialization_alias="storageCrs")
    ] = None
    storage_crs_coordinate_epoch: float | None = None

    @classmethod
    def from_db_item(
        cls, item: models.Collection, url_resolver: UrlResolver
    ) -> "JsonCollection":
        spatial_extent = (
            base.TwoDimensionalSpatialExtent(bbox=item.spatial_extent.bounds)
            if item.spatial_extent
            else None
        )
        temporal_extent = (
            base.TemporalExtent(
                interval=[
                    (
                        item.temporal_extent_begin.isoformat()
                        if item.temporal_extent_begin
                        else None,
                        item.temporal_extent_end.isoformat()
                        if item.temporal_extent_end
                        else None,
                    )
                ]
            )
            if (item.temporal_extent_begin or item.temporal_extent_end)
            else None
        )
        return cls(
            id_=item.resource_identifier,
            title=item.title,
            description=item.description,
            links=[],  # TODO: add links
            extent=base.Extent(spatial=spatial_extent, temporal=temporal_extent)
            if (temporal_extent or spatial_extent)
            else None,
        )

    @classmethod
    def from_potto(
        cls,
        potto_collection: potto_schemas.Collection,
        url_resolver: UrlResolver,
    ) -> "JsonCollection":
        spatial_extent = (
            base.TwoDimensionalSpatialExtent(
                bbox=[potto_collection.spatial_extent.bounds]
            )
            if potto_collection.spatial_extent
            else None
        )
        logger.debug(f"{potto_collection.temporal_extent_begin=}")
        logger.debug(f"{potto_collection.temporal_extent_end=}")
        temporal_extent = (
            base.TemporalExtent(
                interval=[
                    (
                        (
                            potto_collection.temporal_extent_begin.isoformat()
                            if potto_collection.temporal_extent_begin
                            else None
                        ),
                        (
                            potto_collection.temporal_extent_end.isoformat()
                            if potto_collection.temporal_extent_end
                            else None
                        ),
                    )
                ]
            )
            if (
                potto_collection.temporal_extent_begin
                or potto_collection.temporal_extent_end
            )
            else None
        )
        return cls(
            id_=potto_collection.identifier,
            item_type=potto_collection.type_.value,
            title=potto_collection.title,
            description=potto_collection.description,
            links=cls.get_links(
                potto_collection.identifier,
                url_resolver,
                additional_links=potto_collection.additional_links,
            ),
            extent=base.Extent(
                spatial=spatial_extent,
                temporal=temporal_extent,
            ),
            crs=potto_collection.crs,
            storage_crs=potto_collection.storage_crs,
            storage_crs_coordinate_epoch=potto_collection.storage_crs_coordinate_epoch,
        )

    @classmethod
    def get_links(
        cls,
        collection_identifier: str,
        url_resolver: UrlResolver,
        additional_links: list[dict] | None = None,
    ) -> list[base.Link]:
        return [
            *get_base_links(url_resolver),
            base.Link(
                type=constants.MEDIA_TYPE_JSON,
                rel=constants.REL_SELF,
                href=str(
                    url_resolver(
                        "api:collection-get",
                        collection_id=collection_identifier,
                    )
                ),
                title="Collection details",
            ),
            base.Link(
                type=constants.MEDIA_TYPE_HTML,
                rel=constants.REL_ALTERNATE,
                href=str(
                    url_resolver(
                        "collection-get",
                        collection_id=collection_identifier,
                    )
                ),
                title="Collection details",
            ),
            base.Link(
                type=constants.MEDIA_TYPE_GEO_JSON,
                rel=constants.REL_COLLECTION_ITEMS,
                href=str(
                    url_resolver(
                        "api:collection-item-list",
                        collection_id=collection_identifier,
                    )
                ),
            ),
            base.Link(
                type=constants.MEDIA_TYPE_JSON_SCHEMA,
                rel=constants.REL_COLLECTION_SCHEMA,
                href=str(
                    url_resolver(
                        "api:collection-get-schema",
                        collection_id=collection_identifier,
                    )
                ),
            ),
            base.Link(
                type=constants.MEDIA_TYPE_JSON_SCHEMA,
                rel=constants.REL_COLLECTION_QUERYABLES,
                href=str(
                    url_resolver(
                        "api:collection-get-queryables",
                        collection_id=collection_identifier,
                    )
                ),
            ),
            *[base.Link.model_validate(li) for li in additional_links or []],
        ]


class JsonCollectionList(pydantic.BaseModel):
    links: list[base.Link]
    collections: list[JsonCollection]

    @classmethod
    def from_db_items(
        cls, items: list[models.Collection], url_resolver: UrlResolver
    ) -> "JsonCollectionList":
        return cls(
            collections=[JsonCollection.from_db_item(i, url_resolver) for i in items],
            links=[],
        )

    @classmethod
    def from_potto(
        cls, potto_result: potto_schemas.CollectionList, url_resolver: UrlResolver
    ) -> "JsonCollectionList":
        return cls(
            collections=[
                JsonCollection.from_potto(col, url_resolver)
                for col in potto_result.collections
            ],
            links=cls.get_links(url_resolver),
        )

    @classmethod
    def get_links(cls, url_resolver: UrlResolver) -> list[base.Link]:
        return [
            *get_base_links(url_resolver),
            base.Link(
                type=constants.MEDIA_TYPE_JSON,
                rel=constants.REL_SELF,
                href=str(
                    url_resolver(
                        "api:collection-list",
                    )
                ),
                title="Collection list",
            ),
            base.Link(
                type=constants.MEDIA_TYPE_HTML,
                rel=constants.REL_ALTERNATE,
                href=str(
                    url_resolver(
                        "collection-list",
                    )
                ),
                title="Collection list",
            ),
        ]
