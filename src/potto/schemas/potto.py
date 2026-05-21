"""Schemas used for responses of the Potto wrapper."""

import copy
import dataclasses
import datetime as dt
import json
import logging
from typing import Any

import shapely
from pygeoapi.api import API as _PygeoapiApi

from .. import util
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


@dataclasses.dataclass(frozen=True)
class Collection:
    type_: base.CollectionType
    identifier: str
    title: base.Title
    owner: auth.PottoUser
    description: base.MaybeDescription = None
    keywords: base.MaybeKeywords = None
    spatial_extent: base.MaybeShapelyGeometry = None
    crs: list[str] | None = dataclasses.field(default_factory=lambda: [CRS_84])
    storage_crs: str | None = CRS_84
    storage_crs_coordinate_epoch: float | None = None
    custom_page_size: int | None = None
    custom_page_size_max: int | None = None
    temporal_extent_begin: dt.datetime | None = None
    temporal_extent_end: dt.datetime | None = None
    additional_links: list[dict[str, str | dict[str, str]]] | None = None
    providers: dict[str, base.CollectionProvider] | None = None
    queryables: dict[str, Any] | None = None
    schema: dict[str, Any] | None = None

    @classmethod
    def from_pygeoapi(
        cls,
        pygeoapi_collection: dict,
        pygeoapi_api: _PygeoapiApi,
        *,
        pygeoapi_collection_queryables: dict | None = None,
        pygeoapi_collection_schema: dict | None = None,
    ) -> "Collection":
        raw_bbox = pygeoapi_collection.get("extent", {}).get("spatial", {}).get("bbox")
        spatial_extent = shapely.box(*raw_bbox[0]) if raw_bbox else None
        raw_temporal_interval = (
            pygeoapi_collection.get("extent", {})
            .get("temporal", {})
            .get("interval", [[None, None]])
        )
        temporal_begin = (
            dt.datetime.fromisoformat(raw_begin)
            if (raw_begin := raw_temporal_interval[0][0])
            else None
        )
        temporal_end = (
            dt.datetime.fromisoformat(raw_end)
            if (raw_end := raw_temporal_interval[0][1])
            else None
        )
        collection_id = pygeoapi_collection["id"]
        pygeoapi_collection_conf = pygeoapi_api.config["resources"][collection_id]
        parsed_providers = {}
        for raw_provider in pygeoapi_collection_conf.get("providers", []):
            modifiable_provider = dict(raw_provider)
            provider_type = base.ProvidedDataType(modifiable_provider.pop("type"))
            parsed_providers[provider_type] = base.PygeoapiProvider(
                details=base.PygeoapiProviderDetails(
                    python_callable=modifiable_provider.pop("name"),
                    data=modifiable_provider.pop("data"),
                    options=modifiable_provider,
                )
            )
        additional_links = pygeoapi_collection_conf.get("links")
        queryables = None
        if pygeoapi_collection_queryables is not None:
            queryables = copy.deepcopy(pygeoapi_collection_queryables)
            del queryables["$id"]
        schema = None
        if pygeoapi_collection_schema is not None:
            schema = copy.deepcopy(pygeoapi_collection_schema)
            del schema["$id"]
        crs = set(pygeoapi_collection_conf.get("crs", []))
        crs.add(CRS_84)
        return cls(
            type_=util.get_collection_type(pygeoapi_collection_conf),
            identifier=collection_id,
            title=pygeoapi_collection.get("title", ""),
            owner=pygeoapi_collection_conf["owner"],
            description=pygeoapi_collection.get("description", ""),
            keywords=pygeoapi_collection.get("keywords", []),
            spatial_extent=spatial_extent,
            crs=list(crs) if spatial_extent else None,
            storage_crs=pygeoapi_collection_conf.get("storage_crs", CRS_84)
            if spatial_extent
            else None,
            storage_crs_coordinate_epoch=(
                float(coord_epoch)
                if spatial_extent
                and (
                    coord_epoch := pygeoapi_collection_conf.get(
                        "storage_crs_coordinate_epoch"
                    )
                )
                is not None
                else None
            ),
            temporal_extent_begin=temporal_begin,
            temporal_extent_end=temporal_end,
            additional_links=additional_links,
            providers=parsed_providers,
            queryables=queryables,
            schema=schema,
        )


@dataclasses.dataclass(frozen=True)
class Feature:
    id_: str
    properties: dict[str, str | int | float | bool | None]
    geometry: shapely.Geometry

    @classmethod
    def from_pygeoapi_feature(cls, pygeoapi_feature: dict) -> "Feature":
        logger.debug(f"{pygeoapi_feature=}")
        return cls(
            id_=str(pygeoapi_feature["id"]),
            properties={
                k: v for k, v in pygeoapi_feature["properties"].items() if k != "id"
            },
            geometry=shapely.from_geojson(json.dumps(pygeoapi_feature["geometry"])),
        )


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
    filter_: base.FeatureFilter | base.PottoFeatureFilter | None = None
    metadata: dict[str, str] | None = None


@dataclasses.dataclass(frozen=True)
class FeatureResponse:
    collection: Collection
    feature: Feature
    metadata: dict[str, str] | None = None
