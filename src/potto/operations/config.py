import logging
import os
import re

import shapely
from sqlmodel.ext.asyncio.session import AsyncSession

from ..config import PottoSettings
from ..db.models import Collection
from ..schemas.auth import PottoUser
from ..schemas.base import CollectionProvider
from . import metadata as metadata_ops
from . import collections as collection_ops

logger = logging.getLogger(__name__)


async def get_pygeoapi_config(
    session: AsyncSession,
    settings: PottoSettings,
    user: PottoUser | None,
    *,
    collection_identifier: str | None = None,
    collection_page: int = 1,
    collection_page_size: int = 20,
    debug: bool = False,
) -> dict:
    metadata = await metadata_ops.get_server_metadata(session)
    server_conf = {
        "map": {
            "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            "attribution": '&copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap contributors</a>',
        },
        "limits": {
            "default_items": 20,
            "max_items": 50,
            "max_distance_x": None,
            "max_distance_y": None,
            "max_distance_units": None,
            "on_exceed": "throttle",
        },
    }
    data_license = metadata.license or {}
    data_provider = metadata.data_provider or {}
    point_of_contact = metadata.point_of_contact or {}
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
        "logging": {"level": "DEBUG" if debug else "WARNING"},
        "metadata": {
            "identification": {
                "title": metadata.title,
                "description": metadata.description or "",
                "keywords": metadata.keywords or ["geospatial", "data", "api"],
                "keywords_type": metadata.keywords_type or unknown_detail,
                "terms_of_service": metadata.terms_of_service or unknown_detail,
                "url": metadata.url or unknown_detail,
            },
            "license": {
                "name": data_license.get("name", unknown_detail),
                "url": data_license.get("url", unknown_detail),
            },
            "provider": {
                "name": data_provider.get("name", "Organization Name"),
                "url": data_provider.get("url"),
            },
            "contact": {
                "name": point_of_contact.get("name", "Lastname, Firstname"),
                "position": point_of_contact.get("position", "Position Title"),
                "address": point_of_contact.get("address", "Mailing Address"),
                "city": point_of_contact.get("city", "City"),
                "stateorprovince": point_of_contact.get(
                    "stateorprovince", "Administrative Area"
                ),
                "postalcode": point_of_contact.get("postalcode", "Zip or Postal Code"),
                "country": point_of_contact.get("country", "Country"),
                "phone": point_of_contact.get("phone", "+xx-xxx-xxx-xxxx"),
                "fax": point_of_contact.get("fax", "+xx-xxx-xxx-xxxx"),
                "email": point_of_contact.get("email", "you@example.org"),
                "url": point_of_contact.get("url", "Contact URL"),
                "hours": point_of_contact.get("hours", "Mo-Fr 08:00-17:00"),
                "instructions": point_of_contact.get(
                    "instructions", "During hours of service. Off on weekends."
                ),
                "role": point_of_contact.get("role", "pointOfContact"),
            },
        },
        "resources": {},
    }
    collections, total = await collection_ops.paginated_list_collections(
        session,
        user=user,
        identifier_filter=collection_identifier,
        page=collection_page,
        page_size=collection_page_size,
        authorization_backend=settings.get_authorization_backend(),
    )

    for db_collection in collections:
        pygeoapi_config["resources"][db_collection.resource_identifier] = (
            _convert_collection_to_pygeoapi_resource(db_collection)
        )
    # TODO: validate the config
    return pygeoapi_config


def _convert_collection_to_pygeoapi_resource(db_collection: Collection) -> dict:
    links = []
    for collection_link in db_collection.additional_links or []:
        link_ = dict(collection_link)
        type_ = link_.pop("media_type", "")
        links.append({"type": type_, **link_})
    converted_providers = []
    for type_, raw_provider in (db_collection.providers or {}).items():
        provider = CollectionProvider.model_validate(raw_provider)
        raw_data_value = provider.config.data if provider.config else ""
        if isinstance(raw_data_value, str):
            interpolated_data_value = re.sub(
                r"\${?(\w+)}?",
                lambda re_match: os.getenv(re_match.group(1), "ENV_VAR_NOT_FOUND"),
                raw_data_value,
            )
        else:
            interpolated_data_value = raw_data_value
        converted_providers.append(
            {
                "type": type_,
                "data": interpolated_data_value,
                "name": provider.python_callable,
                **(provider.config.options if provider.config else {}),
            }
        )

    extents = {}
    # add any custom extents to the collection - this is done before the
    # adding the 'spatial' and 'temporal' extents to disallow overriding them
    for name, info in (db_collection.additional_extents or {}).items():
        extents[name] = info
    extents = {
        "spatial": {
            "bbox": (
                db_collection.spatial_extent.bounds
                if db_collection.spatial_extent
                else shapely.box(-180, -90, 180, 90).bounds
            ),
            "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
        },
        "temporal": {
            "begin": (
                db_collection.temporal_extent_begin.isoformat()
                if db_collection.temporal_extent_begin
                else None
            ),
            "end": (
                db_collection.temporal_extent_end.isoformat()
                if db_collection.temporal_extent_end
                else None
            ),
        },
    }
    pygeoapi_collection = {
        "type": "collection",
        "title": db_collection.title,
        "description": db_collection.description or "",
        "keywords": db_collection.keywords or [],
        "linked-data": None,
        "links": links,
        "extents": extents,
        "providers": converted_providers,
        # owner is not a property recognized by pygeoapi but we require it in
        # potto.Adding it here takes advantage of the fact that pygeoapi
        # allows additional configuration properties on collections
        "owner": db_collection.owner.to_potto(),
    }
    limits = {
        k: v
        for k, v in {
            "default_items": db_collection.custom_page_size,
            "max_items": db_collection.custom_page_size_max,
        }.items()
        if v is not None
    }
    if limits:
        pygeoapi_collection["limits"] = limits  # ty: ignore[invalid-assignment]
    return pygeoapi_collection
