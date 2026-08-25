"""Schemas used for responses of the Potto wrapper."""

import dataclasses
import datetime as dt
import logging
from typing import Any

import shapely

from ..constants import CRS_84
from . import (
    auth,
    base,
    metadata,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class Pagination:
    page: int
    page_size: int
    total: int


# TODO: Add support for additional extents
@dataclasses.dataclass(frozen=True)
class Collection:
    type_: base.CollectionType
    identifier: str
    title: base.Title
    owner: auth.PottoUser
    crs: list[str]
    description: base.MaybeDescription = None
    keywords: base.MaybeKeywords = None
    spatial_extent: base.MaybeShapelyGeometry = None
    storage_crs: str | None = CRS_84
    storage_crs_coordinate_epoch: float | None = None
    custom_page_size: int | None = None
    custom_page_size_max: int | None = None
    temporal_extent_begin: dt.datetime | None = None
    temporal_extent_end: dt.datetime | None = None
    additional_links: list[dict[str, str | dict[str, str]]] | None = None
    providers: dict[str, base.PottoProvider] | None = None
    queryables: dict[str, Any] | None = None
    schema: dict[str, Any] | None = None


@dataclasses.dataclass(frozen=True)
class Feature:
    id_: str
    properties: dict[str, str | int | float | bool | dt.datetime | None]
    geometry: shapely.Geometry
    crs: str = CRS_84


@dataclasses.dataclass(frozen=True)
class CollectionList:
    collections: list[Collection]
    pagination: Pagination


@dataclasses.dataclass(frozen=True)
class ServerMetadata:
    title: base.Title
    description: base.MaybeDescription = None
    keywords: base.MaybeKeywords = None
    keywords_type: str | None = None
    terms_of_service: base.MaybeDescription = None
    url: str | None = None
    license: metadata.LicenseInformation | None = None
    data_provider: metadata.DataProviderInformation | None = None
    point_of_contact: metadata.PointOfContact | None = None


@dataclasses.dataclass(frozen=True)
class PottoResponse:
    content_type: str
    content: dict | bytes
    metadata: dict[str, str] | None = None


@dataclasses.dataclass(frozen=True)
class LandingPage:
    metadata: ServerMetadata
    collections: CollectionList
    attribution: str | None = None


@dataclasses.dataclass(frozen=True)
class ConformanceDetail:
    conforms_to: list[str]


@dataclasses.dataclass(frozen=True)
class FeatureListResponse:
    collection: Collection
    features: list[Feature]
    pagination: base.PaginationContext
    storage_crs: str = CRS_84
    filter_: base.FeatureFilter | base.PottoFeatureFilter | None = None
    metadata: dict[str, str] | None = None


@dataclasses.dataclass(frozen=True)
class FeatureResponse:
    collection: Collection
    feature: Feature
    storage_crs: str = CRS_84
    metadata: dict[str, str] | None = None
