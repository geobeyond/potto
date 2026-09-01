import asyncio
import babel
import json
import logging
from http import HTTPStatus
from typing import (
    Any,
    cast,
    TYPE_CHECKING,
)

import pydantic
from pydantic.json_schema import JsonSchemaValue
from pygeoapi.api import API as _API
from pygeoapi.api import itemtypes as _itemtypes
from pygeoapi.api import get_collection_schema as _get_collection_schema
import shapely

from ... import exceptions as potto_exceptions
from ...constants import ProvidedDataType
from ...schemas import base
from ...schemas.base import CountedItems
from ...schemas.collections import Collection
from ...schemas.features import (
    Feature,
    PottoFeatureFilter,
)
from ...webapp.requests import PottoRequest

if TYPE_CHECKING:
    from ...config import PottoSettings

logger = logging.getLogger(__name__)


class PygeoapiFeatureProviderConfig(pydantic.BaseModel):
    python_callable: str
    data: str | dict
    options: dict[str, Any]


class PygeoapiFeatureProvider:
    _pygeoapi_api: _API
    collection: Collection
    config: PygeoapiFeatureProviderConfig
    potto_settings: "PottoSettings"

    def __init__(
        self,
        collection: Collection,
        config: PygeoapiFeatureProviderConfig,
        potto_settings: "PottoSettings",
    ) -> None:
        """A feature provider backed by a pygeoapi provider.

        This is a compatibility layer for being able to use pygeoapi's providers
        with Potto.
        """
        self.config = config
        self.collection = collection
        self.potto_settings = potto_settings
        self._pygeoapi_api = _get_pygeoapi_api(collection, config, potto_settings)

    async def list_features(
        self,
        feature_filter: PottoFeatureFilter | None = None,
    ) -> list[Feature]:
        return await asyncio.to_thread(
            _list_features,
            self.collection,
            self._pygeoapi_api,
            feature_filter,
        )

    async def count_items(
        self, feature_filter: PottoFeatureFilter | None = None
    ) -> "CountedItems":
        return await asyncio.to_thread(
            _count_items,
            self.collection,
            self._pygeoapi_api,
            feature_filter,
        )

    async def get_feature(
        self,
        feature_id: str,
        crs: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
    ) -> Feature | None:
        return await asyncio.to_thread(
            _get_feature,
            self.collection,
            self._pygeoapi_api,
            feature_id,
            crs,
        )

    async def get_schema(self) -> JsonSchemaValue:
        return await asyncio.to_thread(
            _get_schema,
            self.collection,
            self._pygeoapi_api,
        )

    async def get_queryables(self) -> JsonSchemaValue:
        return await asyncio.to_thread(
            _get_queryables,
            self.collection,
            self._pygeoapi_api,
        )

    async def get_storage_crs(self) -> base.StorageCrs | None:
        crs = self.config.options.get("storage_crs")
        if crs is None:
            return None
        return base.StorageCrs(
            crs=crs,
            coordinate_epoch=self.config.options.get("storage_crs_coordinate_epoch"),
        )

    async def get_spatial_extent(
        self,
    ) -> base.TwoDimensionalSpatialExtent | base.ThreeDimensionSpatialExtent | None:
        return None

    async def get_temporal_extent(self) -> base.TemporalExtent | None:
        return None

    async def get_additional_extents(self) -> list[base.AdditionalExtent] | None:
        return None


def _list_features(
    collection: Collection,
    pygeoapi_api: _API,
    feature_filter: PottoFeatureFilter | None,
):
    effective_filter = feature_filter or PottoFeatureFilter()
    filter_ = effective_filter.model_dump(by_alias=True, exclude_none=True)
    if bbox_2d := effective_filter.bbox_2d:
        filter_["bbox"] = ",".join(str(v) for v in bbox_2d)
    else:
        del filter_["bbox-crs"]
    pygeoapi_response = _itemtypes.get_collection_items(
        pygeoapi_api,
        PottoRequest(locale=babel.Locale("en"), output_format="json", **filter_),
        dataset=collection.identifier,
    )
    pygeoapi_headers, pygeoapi_status_code, pygeoapi_content = pygeoapi_response
    status_value = cast(HTTPStatus, pygeoapi_status_code).value
    if status_value != 200:
        detail = json.loads(pygeoapi_content).get("description", pygeoapi_content)
        if status_value == 400:
            raise potto_exceptions.PottoBadRequestException(detail)
        raise potto_exceptions.PottoException(str(pygeoapi_response))
    parsed_pygeoapi_content = json.loads(pygeoapi_content)
    return [to_potto_feature(feat) for feat in parsed_pygeoapi_content["features"]]


def _count_items(
    collection: Collection,
    pygeoapi_api: _API,
    feature_filter: PottoFeatureFilter | None,
) -> CountedItems:
    filter_ = (
        feature_filter.model_dump(by_alias=True, exclude_none=True)
        if feature_filter
        else {}
    )
    filter_.pop("bbox-crs", None)
    filter_.pop("bbox", None)
    if feature_filter and (bbox_2d := feature_filter.bbox_2d):
        filter_["bbox"] = ",".join(str(v) for v in bbox_2d)
    pygeoapi_response = _itemtypes.get_collection_items(
        pygeoapi_api,
        PottoRequest(
            locale=babel.Locale("en"),
            output_format="json",
            resulttype="hits",
            **filter_,
        ),
        dataset=collection.identifier,
    )
    _, pygeoapi_status_code, pygeoapi_content = pygeoapi_response
    if cast(HTTPStatus, pygeoapi_status_code).value != 200:
        raise potto_exceptions.PottoException(str(pygeoapi_response))
    parsed = json.loads(pygeoapi_content)
    matched = parsed.get("numberMatched", 0)
    return CountedItems(matched=matched, total=matched)


def _get_feature(
    collection: Collection,
    pygeoapi_api: _API,
    feature_identifier: str,
    crs: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
) -> Feature | None:
    pygeoapi_response = _itemtypes.get_collection_item(
        api=pygeoapi_api,
        request=PottoRequest(  # ty: ignore[invalid-argument-type]
            locale=babel.Locale("en"),
            output_format="json",
            crs=crs,
        ),
        dataset=collection.identifier,
        identifier=feature_identifier,
    )
    pygeoapi_headers, pygeoapi_status_code, pygeoapi_content = pygeoapi_response
    status_value = cast(HTTPStatus, pygeoapi_status_code).value
    if status_value == 404:
        return None
    if status_value != 200:
        detail = json.loads(pygeoapi_content).get("description", pygeoapi_content)
        if status_value == 400:
            raise potto_exceptions.PottoBadRequestException(detail)
        raise potto_exceptions.PottoException(str(pygeoapi_response))
    return to_potto_feature(json.loads(pygeoapi_content))


def _get_queryables(
    collection: Collection,
    pygeoapi_api: _API,
) -> JsonSchemaValue:
    pygeoapi_response = _itemtypes.get_collection_queryables(
        pygeoapi_api,
        PottoRequest(locale=babel.Locale("en"), output_format="json"),
        dataset=collection.identifier,
    )
    _, pygeoapi_status_code, pygeoapi_content = pygeoapi_response
    if cast(HTTPStatus, pygeoapi_status_code).value != 200:
        raise potto_exceptions.PottoException(str(pygeoapi_response))
    return json.loads(pygeoapi_content)


def _get_schema(
    collection: Collection,
    pygeoapi_api: _API,
) -> JsonSchemaValue:
    pygeoapi_response = _get_collection_schema(
        pygeoapi_api,
        PottoRequest(locale=babel.Locale("en"), output_format="json"),
        dataset=collection.identifier,
    )
    _, pygeoapi_status_code, pygeoapi_content = pygeoapi_response
    if cast(HTTPStatus, pygeoapi_status_code).value != 200:
        raise potto_exceptions.PottoException(str(pygeoapi_response))
    return json.loads(pygeoapi_content)


def _get_pygeoapi_api(
    collection: Collection,
    config: PygeoapiFeatureProviderConfig,
    potto_settings: "PottoSettings",
) -> _API:
    pygeoapi_config = _get_pygeoapi_config_single_collection(
        collection, config, potto_settings
    )
    return _API(config=pygeoapi_config, openapi={})


def _get_pygeoapi_config_single_collection(
    collection: Collection,
    provider_config: PygeoapiFeatureProviderConfig,
    settings: "PottoSettings",
) -> dict:
    server_conf = {
        "map": {},
        "limits": {
            "default_items": 20,
            "max_items": 50,
            "max_distance_x": None,
            "max_distance_y": None,
            "max_distance_units": None,
            "on_exceed": "throttle",
        },
    }
    unknown_detail = "unknown"
    pygeoapi_config = {
        "server": {
            "admin": server_conf.get(
                "admin", False
            ),  # we don't use pygeoapi's admin, but rather provide our own
            "languages": settings.languages,
            "limits": server_conf["limits"],
            "map": server_conf["map"],
            "locale_dir": server_conf.get("locale_dir"),
            "url": settings.public_url,
        },
        "logging": {"level": "DEBUG" if settings.debug else "WARNING"},
        "metadata": {
            "identification": {
                "title": "",
                "description": "",
                "keywords": [],
                "keywords_type": unknown_detail,
                "terms_of_service": unknown_detail,
                "url": unknown_detail,
            },
            "license": {
                "name": unknown_detail,
                "url": unknown_detail,
            },
            "provider": {
                "name": unknown_detail,
                "url": unknown_detail,
            },
            "contact": {
                "name": "Lastname, Firstname",
                "position": "Position Title",
                "address": "Mailing Address",
                "city": "City",
                "stateorprovince": "Administrative Area",
                "postalcode": "Zip or Postal Code",
                "country": "Country",
                "phone": "+xx-xxx-xxx-xxxx",
                "fax": "+xx-xxx-xxx-xxxx",
                "email": "you@example.org",
                "url": "Contact URL",
                "hours": "Mo-Fr 08:00-17:00",
                "instructions": "During hours of service. Off on weekends.",
                "role": "pointOfContact",
            },
        },
        "resources": {},
    }
    pygeoapi_config["resources"][collection.identifier] = (
        _convert_collection_to_pygeoapi_resource(collection, provider_config)
    )
    # TODO: validate the config
    return pygeoapi_config


def _convert_collection_to_pygeoapi_resource(
    collection: Collection,
    provider_config: PygeoapiFeatureProviderConfig,
) -> dict:
    links = []
    for collection_link in collection.additional_links or []:
        link_ = dict(collection_link)
        type_ = link_.pop("media_type", "")
        links.append({"type": type_, **link_})
    if collection.providers is None:
        raise potto_exceptions.PottoException(
            f"collection {collection.identifier!r} does not have a feature provider"
        )
    try:
        naive_provider_config = collection.providers[ProvidedDataType.FEATURE.value]
    except KeyError as err:
        raise potto_exceptions.PottoException(
            f"collection {collection.identifier!r} does not have a feature provider"
        ) from err
    if not isinstance(naive_provider_config, base.PottoProvider):
        raise potto_exceptions.PottoException("Unsupported provider")
    # extents = {}
    # # add any custom extents to the collection - this is done before the
    # # adding the 'spatial' and 'temporal' extents to disallow overriding them
    # for name, info in (collection.additional_extents or {}).items():
    #     extents[name] = info
    extents = {
        "spatial": {
            "bbox": (
                collection.spatial_extent.bounds
                if collection.spatial_extent
                else shapely.box(-180, -90, 180, 90).bounds
            ),
            "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
        },
        "temporal": {
            "begin": (
                collection.temporal_extent_begin.isoformat()
                if collection.temporal_extent_begin
                else None
            ),
            "end": (
                collection.temporal_extent_end.isoformat()
                if collection.temporal_extent_end
                else None
            ),
        },
    }
    pygeoapi_collection = {
        "type": "collection",
        "title": collection.title,
        "description": collection.description or "",
        "keywords": collection.keywords or [],
        "linked-data": None,
        "links": links,
        "extents": extents,
        "providers": [
            {
                "type": ProvidedDataType.FEATURE.value,
                "name": provider_config.python_callable,
                "data": provider_config.data,
                **provider_config.options,
            }
        ],
    }
    limits = {
        k: v
        for k, v in {
            "default_items": collection.custom_page_size,
            "max_items": collection.custom_page_size_max,
        }.items()
        if v is not None
    }
    if limits:
        pygeoapi_collection["limits"] = limits  # ty: ignore[invalid-assignment]
    return pygeoapi_collection


def to_potto_feature(pygeoapi_feature: dict) -> Feature:
    logger.debug(f"{pygeoapi_feature=}")
    return Feature(
        id_=str(pygeoapi_feature["id"]),
        properties={
            k: v for k, v in pygeoapi_feature["properties"].items() if k != "id"
        },
        geometry=shapely.from_geojson(json.dumps(pygeoapi_feature["geometry"])),
    )


def pygeoapi_feature_provider_factory(
    collection: Collection,
    raw_config: dict[str, Any],
    potto_config: "PottoSettings",
) -> PygeoapiFeatureProvider:
    config = PygeoapiFeatureProviderConfig.model_validate(raw_config)
    return PygeoapiFeatureProvider(collection, config, potto_config)
