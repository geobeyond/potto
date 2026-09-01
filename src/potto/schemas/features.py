import dataclasses
import datetime as dt
import logging
from typing import (
    Annotated,
    Literal,
    Sequence,
)

import pydantic
import shapely
from starlette.datastructures import QueryParams

from .. import constants
from .collections import Collection
from .pagination import PaginationContext

logger = logging.getLogger(__name__)


def _parse_bbox(
    value: str | Sequence[str | float] | None,
) -> tuple[float, ...] | None:
    """Parse a bbox query value into a 4- or 6-element tuple of floats.

    FastAPI feeds this whatever ``request.query_params.getlist("bbox")`` returned:
    a single comma-separated string wrapped in a one-element list for the
    OGC-required ``bbox=minx,miny,maxx,maxy`` form (``explode: false``), or one raw
    string per element when a client instead repeats the key (``bbox=minx&bbox=miny``).
    """
    if value is None:
        return None
    parts: Sequence[str | float]
    if isinstance(value, str):
        parts = value.split(",")
    elif len(value) == 1 and isinstance(value[0], str) and "," in value[0]:
        parts = value[0].split(",")
    else:
        parts = value
    try:
        coordinates = tuple(float(part) for part in parts)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "bbox must be a comma-separated list of 4 or 6 numbers"
        ) from exc
    if len(coordinates) not in (4, 6):
        raise ValueError("bbox must have exactly 4 or 6 numbers")
    return coordinates


class ItemFilter(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")

    bbox: Annotated[
        str | None,
        pydantic.Field(
            description="Bounding box filter as 'minLon,minLat,maxLon,maxLat'."
        ),
        pydantic.WithJsonSchema(
            {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 4,
                "maxItems": 6,
            }
        ),
    ] = None
    bbox_crs: Annotated[
        str | None,
        pydantic.Field(
            serialization_alias="bbox-crs",
            description="CRS of the bbox coordinates, as a URI.",
        ),
    ] = None
    cql_text: Annotated[
        str | None, pydantic.Field(description="CQL2 text filter expression.")
    ] = None
    datetime_: Annotated[
        str | None,
        pydantic.Field(
            serialization_alias="datetime",
            description="Temporal filter as RFC 3339 instant or interval ('/' separated).",
        ),
    ] = None
    vendor_specific_parameters: Annotated[
        dict[str, str] | None,
        pydantic.Field(
            serialization_alias="vendorSpecificParameters",
            description="Additional query properties to pass through.",
        ),
        pydantic.WithJsonSchema(
            {"anyOf": [{"type": "object", "maxProperties": 10}, {"type": "null"}]}
        ),
    ] = None
    filter_: Annotated[
        str | None,
        pydantic.Field(serialization_alias="filter", description="Filter expression."),
    ] = None
    filter_lang: Annotated[
        str | None,
        pydantic.Field(
            serialization_alias="filter-lang",
            description="Filter language identifier (e.g. 'cql2-text', 'cql2-json').",
        ),
    ] = None
    filter_crs_uri: Annotated[
        str | None,
        pydantic.Field(description="CRS URI for filter geometry coordinates."),
    ] = None
    limit: Annotated[
        int, pydantic.Field(description="Maximum number of items to return.", ge=1)
    ] = 20
    locale: Annotated[
        str | None,
        pydantic.Field(
            alias="language", description="Preferred response language as a BCP 47 tag."
        ),
    ] = None
    offset: Annotated[
        int,
        pydantic.Field(description="Number of items to skip before returning results."),
    ] = 0
    query: Annotated[
        str | None, pydantic.Field(description="Full-text search query string.")
    ] = None
    result_type: Annotated[
        Literal["hits", "results"],
        pydantic.Field(
            description="Response type: 'results' returns items, 'hits' returns only the count."
        ),
    ] = "results"
    skip_geometry: Annotated[
        bool | None,
        pydantic.Field(
            serialization_alias="skipGeometry",
            description="If true, geometry is omitted from the response.",
        ),
    ] = None
    sort_by: Annotated[
        str | None,
        pydantic.Field(
            serialization_alias="sortby",
            description="Sort expression, e.g. '+name,-date'.",
        ),
    ] = None


class FeatureFilter(ItemFilter):
    crs: Annotated[
        str | None, pydantic.Field(description="CRS URI for geometry coordinates.")
    ] = None

    @classmethod
    def from_query_parameters(
        cls,
        params: QueryParams,
    ) -> "FeatureFilter":
        return cls(
            bbox=params.get("bbox"),
            bbox_crs=params.get("bbox-crs"),
            crs=params.get("crs"),
            datetime_=params.get("datetime"),
            filter_=params.get("filter"),
            filter_crs_uri=params.get("filter-crs"),
            filter_lang=params.get("filter-lang"),
            limit=int(params.get("limit", 20)),
            offset=int(params.get("offset", 0)),
            vendor_specific_parameters=dict(params),
            query=params.get("q"),
            result_type="hits" if params.get("resulttype") == "hits" else "results",
            sort_by=params.get("sortby"),
            skip_geometry=(
                True
                if params.get("skipGeometry", "").lower()
                in ("true", "yes", "on", "t", "1")
                else False
            ),
        )


class PottoFeatureFilter(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(serialize_by_alias=True, extra="allow")
    bbox: Annotated[
        tuple[float, ...] | None,
        pydantic.BeforeValidator(_parse_bbox),
        pydantic.Field(
            description=(
                "Bounding box filter as 'minx,miny,maxx,maxy' or, for a 3D bbox, "
                "'minx,miny,minz,maxx,maxy,maxz'."
            ),
        ),
        pydantic.WithJsonSchema(
            {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 4,
                "maxItems": 6,
                "nullable": True,
            }
        ),
    ] = None
    bbox_crs: Annotated[
        str,
        pydantic.Field(
            alias="bbox-crs",
            description="CRS of the bbox coordinates, as a URI.",
        ),
    ] = constants.CRS_84
    crs: Annotated[
        str,
        pydantic.Field(description="CRS URI for the response geometry coordinates."),
    ] = constants.CRS_84
    datetime_: Annotated[
        str | None,
        pydantic.Field(
            alias="datetime",
            description=(
                "Temporal filter as an RFC 3339 instant, or an interval of two "
                "instants separated by '/' where either side may be '..' for an "
                "open end."
            ),
        ),
    ] = None
    limit: Annotated[
        int, pydantic.Field(description="Maximum number of items to return.", ge=1)
    ] = 20
    offset: Annotated[
        int,
        pydantic.Field(
            description="Number of items to skip before returning results.", ge=0
        ),
    ] = 0
    filter_: Annotated[
        str | None,
        pydantic.Field(alias="filter", description="Filter expression."),
    ] = None
    filter_lang: Annotated[
        str | None,
        pydantic.Field(
            alias="filter-lang",
            description="Filter language identifier (e.g. 'cql2-text', 'cql2-json').",
        ),
    ] = None

    @property
    def bbox_2d(self) -> tuple[float, float, float, float] | None:
        """The horizontal (x/y) extent of ``bbox``, dropping any z-min/z-max.

        OGC API - Features allows a 6-element 3D bbox (minx,miny,minz,maxx,maxy,maxz);
        none of potto's feature providers filter on the z axis, so this is the 2D
        extent they actually use.
        """
        if self.bbox is None:
            return None
        if len(self.bbox) == 6:
            minx, miny, _minz, maxx, maxy, _maxz = self.bbox
        else:
            minx, miny, maxx, maxy = self.bbox
        return (minx, miny, maxx, maxy)

    @classmethod
    def from_feature_filter(cls, feature_filter: FeatureFilter) -> "PottoFeatureFilter":
        bbox = None
        if raw_bbox := feature_filter.bbox.split(",") if feature_filter.bbox else None:
            try:
                bbox = (
                    float(raw_bbox[0]),
                    float(raw_bbox[1]),
                    float(raw_bbox[2]),
                    float(raw_bbox[3]),
                )
            except IndexError:
                bbox = None
        return cls(
            bbox=bbox,
            bbox_crs=feature_filter.bbox_crs or constants.CRS_84,
            crs=feature_filter.crs or constants.CRS_84,
            limit=feature_filter.limit,
            offset=feature_filter.offset,
            filter_=feature_filter.filter_,
            filter_lang=feature_filter.filter_lang,
        )


@dataclasses.dataclass(frozen=True)
class Feature:
    id_: str
    properties: dict[str, str | int | float | bool | dt.datetime | None]
    geometry: shapely.Geometry
    crs: str = constants.CRS_84


@dataclasses.dataclass(frozen=True)
class AugmentedFeature:
    collection: Collection
    feature: Feature
    metadata: dict[str, str] | None = None


@dataclasses.dataclass(frozen=True)
class FeatureList:
    collection: Collection
    features: list[Feature]
    pagination: PaginationContext
    storage_crs: str = constants.CRS_84
    filter_: FeatureFilter | PottoFeatureFilter | None = None
    metadata: dict[str, str] | None = None
