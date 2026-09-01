import dataclasses
import datetime as dt
import logging
from typing import (
    Annotated,
    Any,
    Literal,
)

import pydantic

from .auth import PottoUser
from .base import (
    AdditionalExtent,
    CollectionIdentifier,
    MaybeDescription,
    MaybeKeywords,
    MaybeShapelyGeometry,
    PottoProvider,
    Title,
)
from .pagination import Pagination

from ..constants import (
    CollectionType,
    CRS_84,
)

logger = logging.getLogger(__name__)


# TODO: Add support for additional extents
@dataclasses.dataclass(frozen=True)
class Collection:
    type_: CollectionType
    identifier: str
    title: Title
    owner: PottoUser
    crs: list[str]
    description: MaybeDescription = None
    keywords: MaybeKeywords = None
    spatial_extent: MaybeShapelyGeometry = None
    storage_crs: str | None = CRS_84
    storage_crs_coordinate_epoch: float | None = None
    custom_page_size: int | None = None
    custom_page_size_max: int | None = None
    temporal_extent_begin: dt.datetime | None = None
    temporal_extent_end: dt.datetime | None = None
    additional_links: list[dict[str, str | dict[str, str]]] | None = None
    providers: dict[str, PottoProvider] | None = None
    queryables: dict[str, Any] | None = None
    schema: dict[str, Any] | None = None


@dataclasses.dataclass(frozen=True)
class AugmentedCollection:
    collection: Collection
    metadata: dict[str, str] | None = None


@dataclasses.dataclass(frozen=True)
class CollectionList:
    collections: list[Collection]
    pagination: Pagination


class CollectionCreate(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)
    resource_identifier: CollectionIdentifier
    owner_id: str
    is_public: bool = False
    collection_type: CollectionType
    title: Title
    description: MaybeDescription = None
    keywords: MaybeKeywords = None
    spatial_extent: MaybeShapelyGeometry = None
    spatial_extent_crs: str | None = None
    crs: list[str] | None = None
    storage_crs: str | None = None
    storage_crs_coordinate_epoch: str | None = None
    temporal_extent_begin: dt.datetime | None = None
    temporal_extent_end: dt.datetime | None = None
    additional_extents: list[AdditionalExtent] | None = None
    custom_page_size: Annotated[int | None, pydantic.Field(ge=1)] = None
    custom_page_size_max: Annotated[int | None, pydantic.Field(ge=1)] = None
    additional_links: Annotated[
        list[dict[str, str | dict[str, str]]] | None,
        pydantic.WithJsonSchema(
            {
                "anyOf": [
                    {"type": "array", "items": {"type": "object", "maxProperties": 10}},
                    {"type": "null"},
                ]
            }
        ),
    ] = None
    providers: Annotated[
        dict[str, PottoProvider] | None,
        pydantic.WithJsonSchema(
            {
                "anyOf": [
                    {
                        "allOf": [
                            {"type": "object", "maxProperties": 10},
                            {
                                "additionalProperties": {
                                    "$ref": "#/components/schemas/PottoProvider"
                                }
                            },
                        ]
                    },
                    {"type": "null"},
                ]
            }
        ),
    ] = None


class CollectionAccessGrant(pydantic.BaseModel):
    role: Literal["editor", "viewer"]


class CollectionUpdate(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)
    owner_id: str | None = None
    is_public: bool | None = None
    collection_type: CollectionType | None = None
    title: Title | None = None
    description: MaybeDescription = None
    keywords: MaybeKeywords = None
    spatial_extent: MaybeShapelyGeometry = None
    spatial_extent_crs: str | None = None
    crs: list[str] | None = None
    storage_crs: str | None = None
    storage_crs_coordinate_epoch: str | None = None
    temporal_extent_begin: dt.datetime | None = None
    temporal_extent_end: dt.datetime | None = None
    additional_extents: list[AdditionalExtent] | None = None
    custom_page_size: Annotated[int | None, pydantic.Field(ge=1)] = None
    custom_page_size_max: Annotated[int | None, pydantic.Field(ge=1)] = None
    additional_links: list[dict[str, str | dict[str, str]]] | None = None
    providers: dict[str, PottoProvider] | None = None
