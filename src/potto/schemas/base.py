import dataclasses
import enum
import logging
import pydantic
import typing

import shapely
from geoalchemy2 import WKBElement
from geoalchemy2.shape import to_shape
from starlette.datastructures import QueryParams

from .. import constants

if typing.TYPE_CHECKING:
    from .pygeoapi_config import ExtentConfig

logger = logging.getLogger(__name__)


def _serialize_localizable_field(value: dict[str, str] | str, _info):
    """Serialize a localizable field.

    Localizable fields use a JSONB type, which is not serialized by default, hence
    the need for this function.
    """
    return value


def _serialize_localizable_list_field(value: dict[str, list[str]] | list[str], _info):
    """Serialize a localizable list field.

    Localizable fields use a JSONB type, which is not serialized by default, hence
    the need for this function.
    """
    return value


def to_shapely(
    value: str | WKBElement | shapely.Geometry | None,
) -> shapely.Geometry | None:
    logger.debug(f"{value=}")
    if not value:
        return None
    elif isinstance(value, shapely.Geometry):
        return value
    elif isinstance(value, str):
        return shapely.from_wkt(value)
    else:
        return to_shape(value)


CollectionIdentifier = typing.Annotated[
    str, pydantic.Field(min_length=3, max_length=100, pattern=r"[a-zA-Z][\w\-]*")
]


MaybeShapelyGeometry = typing.Annotated[
    shapely.Geometry | None,
    pydantic.BeforeValidator(to_shapely),
    pydantic.PlainSerializer(
        lambda geom: shapely.to_geojson(geom) if geom else None, return_type=str
    ),
    pydantic.WithJsonSchema(
        {"anyOf": [{"type": "string", "title": "WKT Geometry"}, {"type": "null"}]}
    ),
]


class CollectionType(str, enum.Enum):
    COVERAGE = "coverage"
    FEATURE_COLLECTION = "feature"
    RECORD_COLLECTION = "record"


class ProvidedDataType(str, enum.Enum):
    COVERAGE = "coverage"
    EDR = "edr"
    FEATURE = "feature"
    MAP = "map"
    RECORD = "record"
    STAC = "stac"
    TILE = "tile"


# Localizable fields store either a plain string or a locale-keyed dict (e.g. {"en": "…",
# "it": "…"}). WithJsonSchema overrides the generated schema to avoid the unconstrained
# additionalProperties that Pydantic would otherwise emit for dict[str, …].
Title = typing.Annotated[
    dict[str, str] | str,
    pydantic.PlainSerializer(_serialize_localizable_field),
    pydantic.WithJsonSchema(
        {"anyOf": [{"type": "object", "maxProperties": 200}, {"type": "string"}]}
    ),
]
MaybeDescription = typing.Annotated[
    dict[str, str] | str | None,
    pydantic.PlainSerializer(_serialize_localizable_field),
    pydantic.WithJsonSchema(
        {
            "anyOf": [
                {"type": "object", "maxProperties": 200},
                {"type": "string"},
                {"type": "null"},
            ]
        }
    ),
]
MaybeKeywords = typing.Annotated[
    dict[str, list[str]] | list[str] | None,
    pydantic.PlainSerializer(_serialize_localizable_list_field),
    pydantic.WithJsonSchema(
        {
            "anyOf": [
                {"type": "object", "maxProperties": 200},
                {"items": {"type": "string"}, "type": "array"},
                {"type": "null"},
            ]
        }
    ),
]


@dataclasses.dataclass
class CountedItems:
    matched: int
    total: int


class Link(pydantic.BaseModel):
    media_type: str = pydantic.Field(alias="type")
    rel: str
    href: str
    title: str | None = None
    href_lang: str | None = None
    length: int | None = None

    def serialize_as_http_header(self) -> str:
        result = f'<{self.href}>; rel="{self.rel}"; type="{self.media_type}"'
        extra = [
            ("title", self.title),
            ("hreflang", self.href_lang),
            ("length", self.length),
        ]
        if suffix := "; ".join(f'{k}="{v}"' for k, v in extra if v):
            result = "; ".join((result, suffix))
        return result


class TwoDimensionalSpatialExtent(pydantic.BaseModel):
    bbox: list[tuple[float, float, float, float]]
    crs: str = constants.CRS_84


class ThreeDimensionSpatialExtent(pydantic.BaseModel):
    bbox: list[tuple[float, float, float, float, float, float]]
    crs: str = constants.CRS_84h


class TemporalExtent(pydantic.BaseModel):
    interval: list[tuple[str | None, str | None]]
    trs: str = constants.GREGORIAN


class Extent(pydantic.BaseModel):
    spatial: TwoDimensionalSpatialExtent | ThreeDimensionSpatialExtent | None = None
    temporal: TemporalExtent | None = None

    @classmethod
    def from_config(cls, extent_config: "ExtentConfig") -> "Extent":
        if extent_config.temporal:
            temporal_conf = TemporalExtent(
                interval=[
                    (
                        begin.strftime("%Y-%m-%DT%H:%M:%SZ")
                        if (begin := extent_config.temporal.begin)
                        else None,
                        end.strftime("%Y-%m-%DT%H:%M:%SZ")
                        if (end := extent_config.temporal.end)
                        else None,
                    )
                ],
                trs=extent_config.temporal.trs,
            )
        else:
            temporal_conf = None
        first_bbox = extent_config.spatial.bbox
        if len(first_bbox) > 5:
            spatial_conf = ThreeDimensionSpatialExtent(
                bbox=[
                    (
                        first_bbox[0],
                        first_bbox[1],
                        first_bbox[2],
                        first_bbox[3],
                        first_bbox[4],
                        first_bbox[5],
                    )
                ],
                crs=extent_config.spatial.crs,
            )
        else:
            spatial_conf = TwoDimensionalSpatialExtent(
                bbox=[(first_bbox[0], first_bbox[1], first_bbox[2], first_bbox[3])],
                crs=extent_config.spatial.crs,
            )

        return cls(
            spatial=spatial_conf,
            temporal=temporal_conf,
        )


class AdditionalExtent(pydantic.BaseModel):
    name: str
    begin: int | float | str | None = None
    end: int | float | str | None = None
    unit_name: str | None = None


@dataclasses.dataclass(frozen=True)
class StorageCrs:
    crs: str
    coordinate_epoch: str | None = None


class PottoProvider(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")
    provider_name: str
    config: typing.Annotated[
        dict[str, typing.Any],
        pydantic.WithJsonSchema({"type": "object", "maxProperties": 10}),
    ]


class PaginationContext(pydantic.BaseModel):
    limit: int
    number_matched: int
    number_returned: int
    offset: int

    def get_links(
        self,
        base_url: str,
        target_media_type: str = constants.MEDIA_TYPE_JSON,
        additional_query_params: dict[str, str] | None = None,
    ) -> list[Link]:
        additional = (
            "&".join(
                f"{k}={','.join(str(x) for x in v) if isinstance(v, (list, tuple)) else v}"
                for k, v in additional_query_params.items()
            )
            if additional_query_params
            else None
        )
        result = []
        if self.offset > 0:
            prev_offset = max(0, self.offset - self.limit)
            result.append(
                Link(
                    type=target_media_type,
                    rel="prev",
                    href=f"{base_url}?offset={prev_offset}{f'&{additional}' if additional else ''}",
                    title="Previous page of this resultset",
                )
            )
        if self.number_matched > self.offset + self.limit:
            next_offset = self.offset + self.limit
            result.append(
                Link(
                    type=target_media_type,
                    rel="next",
                    href=f"{base_url}?offset={next_offset}{f'&{additional}' if additional else ''}",
                    title="Next page of this resultset",
                )
            )
        return result


class ItemFilter(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")

    bbox: typing.Annotated[
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
    bbox_crs: typing.Annotated[
        str | None,
        pydantic.Field(
            serialization_alias="bbox-crs",
            description="CRS of the bbox coordinates, as a URI.",
        ),
    ] = None
    cql_text: typing.Annotated[
        str | None, pydantic.Field(description="CQL2 text filter expression.")
    ] = None
    datetime_: typing.Annotated[
        str | None,
        pydantic.Field(
            serialization_alias="datetime",
            description="Temporal filter as RFC 3339 instant or interval ('/' separated).",
        ),
    ] = None
    vendor_specific_parameters: typing.Annotated[
        dict[str, str] | None,
        pydantic.Field(
            serialization_alias="vendorSpecificParameters",
            description="Additional query properties to pass through.",
        ),
        pydantic.WithJsonSchema(
            {"anyOf": [{"type": "object", "maxProperties": 10}, {"type": "null"}]}
        ),
    ] = None
    filter_: typing.Annotated[
        str | None,
        pydantic.Field(serialization_alias="filter", description="Filter expression."),
    ] = None
    filter_lang: typing.Annotated[
        str | None,
        pydantic.Field(
            serialization_alias="filter-lang",
            description="Filter language identifier (e.g. 'cql2-text', 'cql2-json').",
        ),
    ] = None
    filter_crs_uri: typing.Annotated[
        str | None,
        pydantic.Field(description="CRS URI for filter geometry coordinates."),
    ] = None
    limit: typing.Annotated[
        int, pydantic.Field(description="Maximum number of items to return.", ge=1)
    ] = 20
    locale: typing.Annotated[
        str | None,
        pydantic.Field(
            alias="language", description="Preferred response language as a BCP 47 tag."
        ),
    ] = None
    offset: typing.Annotated[
        int,
        pydantic.Field(description="Number of items to skip before returning results."),
    ] = 0
    query: typing.Annotated[
        str | None, pydantic.Field(description="Full-text search query string.")
    ] = None
    result_type: typing.Annotated[
        typing.Literal["hits", "results"],
        pydantic.Field(
            description="Response type: 'results' returns items, 'hits' returns only the count."
        ),
    ] = "results"
    select_properties: typing.Annotated[
        list[str] | None,
        pydantic.Field(
            alias="properties",
            description="List of item properties to include in the response.",
        ),
    ] = None
    skip_geometry: typing.Annotated[
        bool | None,
        pydantic.Field(
            serialization_alias="skipGeometry",
            description="If true, geometry is omitted from the response.",
        ),
    ] = None
    sort_by: typing.Annotated[
        str | None,
        pydantic.Field(
            serialization_alias="sortby",
            description="Sort expression, e.g. '+name,-date'.",
        ),
    ] = None


class FeatureFilter(ItemFilter):
    crs: typing.Annotated[
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
    bbox: tuple[float, float, float, float] | None = None
    bbox_crs: typing.Annotated[
        str,
        pydantic.Field(
            serialization_alias="bbox-crs",
            description="CRS of the bbox coordinates, as a URI.",
        ),
    ] = constants.CRS_84
    crs: str = constants.CRS_84
    limit: typing.Annotated[
        int, pydantic.Field(description="Maximum number of items to return.", ge=1)
    ] = 20
    offset: typing.Annotated[
        int,
        pydantic.Field(
            description="Number of items to skip before returning results.", ge=0
        ),
    ] = 0
    properties: list[str] | None = None
    filter_: typing.Annotated[
        str | None,
        pydantic.Field(serialization_alias="filter", description="Filter expression."),
    ] = None
    filter_lang: typing.Annotated[
        str | None,
        pydantic.Field(
            serialization_alias="filter-lang",
            description="Filter language identifier (e.g. 'cql2-text', 'cql2-json').",
        ),
    ] = None

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
            properties=feature_filter.select_properties,
            filter_=feature_filter.filter_,
            filter_lang=feature_filter.filter_lang,
        )


class PottoHealthCheck(pydantic.BaseModel):
    status: typing.Literal["ok", "error"]
    database: typing.Literal["ok", "error"]
