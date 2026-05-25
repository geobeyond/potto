import datetime as dt
import logging
from typing import (
    Annotated,
    Literal,
)

import pydantic

from .base import (
    AdditionalExtent,
    PottoProvider,
    CollectionType,
    MaybeDescription,
    MaybeKeywords,
    MaybeShapelyGeometry,
    Title,
)

logger = logging.getLogger(__name__)


class CollectionCreate(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)
    resource_identifier: str = pydantic.Field(min_length=3, max_length=100)
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
