import datetime as dt
from typing import Literal

import pydantic
import shapely


class LocalizableConfigString(pydantic.RootModel):
    root: dict[str, str]

    def get_value(self, language: str | None = None) -> str:
        default_value = list(self.root.values())[0]
        return (
            self.root.get(language, default_value)
            if language is not None
            else default_value
        )

    @classmethod
    def from_potto_db(cls, value: str | dict[str, str]) -> "LocalizableConfigString":
        return cls({"en": value} if isinstance(value, str) else value.copy())

    @classmethod
    def from_pygeoapi_config(
        cls, value: str | dict[str, str]
    ) -> "LocalizableConfigString":
        return cls.from_potto_db(value)


class LocalizableConfigStringList(pydantic.RootModel):
    root: dict[str, list[str]]

    def get_value(self, language: str | None = None) -> list[str]:
        default_value = list(self.root.values())[0]
        return (
            self.root.get(language, default_value)
            if language is not None
            else default_value
        )

    @classmethod
    def from_potto_db(
        cls, value: list[str] | dict[str, list[str]]
    ) -> "LocalizableConfigStringList":
        if isinstance(value, list):
            return cls({"en": value})
        else:
            return cls(value.copy())

    @classmethod
    def from_pygeoapi_config(
        cls, value: list[str] | dict[str, list[str]]
    ) -> "LocalizableConfigStringList":
        return cls.from_potto_db(value)


#
#
# class ServerMetadataIdentificationConfig(pydantic.BaseModel):
#     title: Title
#     description: Description
#     keywords: Keywords
#     keywords_type: str
#     terms_of_service: str
#     url: str
#
#     @classmethod
#     def from_pygeoapi_config(
#             cls,
#             identification_config: dict
#     ) -> "ServerMetadataIdentificationConfig":
#         return cls(
#             title=identification_config["title"],
#             description=identification_config["description"],
#             keywords=identification_config["keywords"],
#             keywords_type=identification_config["keywords_type"],
#             terms_of_service=identification_config["terms_of_service"],
#             url=identification_config["url"],
#         )


class LimitsConfig(pydantic.BaseModel):
    max_items: int = 100
    default_items: int = 10
    max_distance_x: float = 100
    max_distance_y: float = 100
    max_distance_units: str = ""
    on_exceed: Literal["error", "throttle"] = "throttle"

    @classmethod
    def from_pygeoapi_config(cls, limits_config: dict) -> "LimitsConfig":
        return cls(
            max_items=limits_config.get("max_items", 100),
            default_items=limits_config.get("default_items", 10),
            max_distance_x=limits_config.get("max_distance", {}).get("x", 100),
            max_distance_y=limits_config.get("max_distance", {}).get("y", 100),
            max_distance_units=limits_config.get("max_distance_units", ""),
            on_exceed=limits_config.get("on_exceed", "throttle"),
        )

    def as_pygeoapi_config(self) -> dict:
        return {
            "max_items": self.max_items,
            "default_items": self.default_items,
            "max_distance": {
                "x": self.max_distance_x,
                "y": self.max_distance_y,
            },
            "max_distance_units": self.max_distance_units,
            "on_exceed": self.on_exceed,
        }


class LinkConfig(pydantic.BaseModel):
    type_: str
    rel: str
    href: str
    title: str | dict[str, str] | None = None
    href_lang: str | None = None
    length: int | None = None

    @classmethod
    def from_potto_db(cls, link_config: dict) -> "LinkConfig":
        return cls(
            type_=link_config["media_type"],
            rel=link_config["rel"],
            href=link_config["href"],
            title=list(link_config.get("title", {}).values())[0]
            if link_config
            else None,
            href_lang=link_config.get("hreflang"),
            length=int(length) if (length := link_config.get("length")) else None,
        )

    @classmethod
    def from_pygeoapi_config(cls, link_config: dict) -> "LinkConfig":
        return cls(
            type_=link_config["type"],
            rel=link_config["rel"],
            href=link_config["href"],
            title=link_config.get("title"),
            href_lang=link_config.get("hreflang"),
            length=int(length) if (length := link_config.get("length")) else None,
        )


class SpatialExtentConfig(pydantic.BaseModel):
    bbox: list[float]
    crs: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"


class TemporalExtentConfig(pydantic.BaseModel):
    begin: dt.datetime | None
    end: dt.datetime | None
    trs: str = "http://www.opengis.net/def/uom/ISO-8601/0/Gregorian"


class ExtentConfig(pydantic.BaseModel):
    spatial: SpatialExtentConfig
    temporal: TemporalExtentConfig | None = None

    @classmethod
    def from_potto_db(
        cls,
        spatial_extent: shapely.Polygon | None,
        temporal_extent: tuple[dt.datetime | None, dt.datetime | None],
    ):
        bbox = spatial_extent if spatial_extent else shapely.box(-180, -90, 180, 90)
        return cls(
            spatial=SpatialExtentConfig(
                bbox=bbox.bounds,
            ),
            temporal=TemporalExtentConfig(
                begin=temporal_extent[0],
                end=temporal_extent[1],
            ),
        )

    @classmethod
    def from_pygeoapi_config(cls, extent_config: dict) -> "ExtentConfig":
        return cls(
            spatial=SpatialExtentConfig(
                bbox=extent_config["spatial"]["bbox"],
                crs=extent_config["spatial"].get(
                    "crs", "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
                ),
            ),
            temporal=TemporalExtentConfig(
                begin=raw_temporal_config.get("begin"),
                end=raw_temporal_config.get("end"),
                trs=raw_temporal_config.get(
                    "trs", "http://www.opengis.net/def/uom/ISO-8601/0/Gregorian"
                ),
            )
            if (raw_temporal_config := extent_config.get("temporal"))
            else None,
        )


class FormatConfig(pydantic.BaseModel):
    name: str
    media_type: str

    @classmethod
    def from_pygeoapi_config(cls, format_config: dict) -> "FormatConfig":
        return cls(name=format_config["name"], media_type=format_config["mimetype"])


class ProviderConfig(pydantic.BaseModel):
    type_: Literal[
        "coverage",
        "edr",
        "feature",
        "map",
        "record",
        "stac",
        "tile",
    ]
    name: str
    data_: str | dict
    is_default_for_collection: bool = False
    is_editable: bool = False
    table: str | None = None
    id_field: str | None = None
    uri_field: str | None = None
    geometry_x_field: str | None = None
    geometry_y_field: str | None = None
    time_field: str | None = None
    title_field: str | None = None
    default_format: FormatConfig | None = None
    extra_options: dict | None = None
    properties_to_return: list[str] | None = pydantic.Field(min_length=1)
    supported_crs: list[str] | None = None
    storage_crs: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
    storage_crs_coordinate_epoch: str | None = None
    include_extra_query_parameters: bool = True

    @classmethod
    def from_potto_db(cls, provider_config: dict) -> "ProviderConfig":
        return cls(
            type_=provider_config["type"],
            name=provider_config["name"],
            data_=provider_config["data"],
            is_default_for_collection=provider_config.get("default", False),
            is_editable=provider_config.get("editable", False),
            table=provider_config.get("table"),
            id_field=provider_config.get("id_field"),
            uri_field=provider_config.get("uri_field"),
            geometry_x_field=provider_config.get("geometry", {}).get("x_field"),
            geometry_y_field=provider_config.get("geometry", {}).get("y_field"),
            time_field=provider_config.get("time_field"),
            title_field=provider_config.get("title_field"),
            default_format=FormatConfig.from_pygeoapi_config(raw_format)
            if (raw_format := provider_config.get("format"))
            else None,
            extra_options=provider_config.get("options"),
            properties_to_return=provider_config.get("properties"),
            supported_crs=provider_config.get("crs"),
            storage_crs=provider_config.get(
                "storage_crs", "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
            ),
            storage_crs_coordinate_epoch=provider_config.get(
                "storage_crs_coordinate_epoch"
            ),
            include_extra_query_parameters=provider_config.get(
                "include_extra_query_parameters", True
            ),
        )

    @classmethod
    def from_pygeoapi_config(cls, provider_config: dict) -> "ProviderConfig":
        return cls.from_potto_db(provider_config)


class ItemCollectionConfig(pydantic.BaseModel):
    identifier: str
    type_: Literal["collection"]
    title: LocalizableConfigString
    description: LocalizableConfigString
    keywords: LocalizableConfigStringList
    extents: ExtentConfig
    providers: list[ProviderConfig]
    visibility: Literal["default", "hidden"] = "default"
    linked_data: dict | None = None
    links: list[LinkConfig] | None = None
    limits: LimitsConfig | None = None

    def list_provider_configs(
        self,
        type_: Literal[
            "feature",
            "coverage",
            "record",
            "map",
            "tile",
            "edr",
            "stac",
        ]
        | None = None,
    ):
        return (
            [p for p in self.providers if p.type_ == type_] if type_ else self.providers
        )

    def get_default_provider_config(
        self,
        type_: Literal[
            "feature",
            "coverage",
            "record",
            "map",
            "tile",
            "edr",
            "stac",
        ]
        | None = None,
    ) -> ProviderConfig:
        for provider_conf in self.providers:
            if provider_conf.is_default_for_collection:
                return provider_conf
        if type_:
            return [p for p in self.providers if p.type_ == type_][0]
        else:
            return self.providers[0]

    @classmethod
    def from_pygeoapi_config(
        cls, identifier: str, collection_config: dict
    ) -> "ItemCollectionConfig":
        return cls(
            identifier=identifier,
            type_=collection_config["type"],
            title=LocalizableConfigString.from_pygeoapi_config(
                collection_config["title"]
            ),
            description=LocalizableConfigString.from_pygeoapi_config(
                collection_config["description"]
            ),
            keywords=LocalizableConfigStringList.from_pygeoapi_config(
                collection_config["keywords"]
            ),
            extents=ExtentConfig.from_pygeoapi_config(collection_config["extents"]),
            providers=[
                ProviderConfig.from_pygeoapi_config(raw_provider)
                for raw_provider in collection_config["providers"]
            ],
            visibility=collection_config.get("visibility", "default"),
            linked_data=collection_config.get("linked_data"),
            links=[LinkConfig.from_pygeoapi_config(raw_link) for raw_link in raw_links]
            if (raw_links := collection_config.get("links"))
            else None,
            limits=LimitsConfig.from_pygeoapi_config(raw_limits)
            if (raw_limits := collection_config.get("limits"))
            else None,
        )
