import logging

import shapely

from ..config import PottoSettings
from ..schemas.auth import PottoUser
from ..schemas.collections import Collection, CollectionFilter
from ..util import interpolate_configuration_value

logger = logging.getLogger(__name__)


async def get_pygeoapi_config(
    settings: PottoSettings,
    user: PottoUser | None,
    *,
    collection_identifier: str | None = None,
    collection_page: int = 1,
    collection_page_size: int = 20,
    debug: bool = False,
) -> dict:
    metadata = await settings.get_server_metadata_manager().get_server_metadata()
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
    data_license = metadata.license
    data_provider = metadata.data_provider
    point_of_contact = metadata.point_of_contact
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
                "name": (data_license.name if data_license else None) or unknown_detail,
                "url": (data_license.url if data_license else None) or unknown_detail,
            },
            "provider": {
                "name": (data_provider.name if data_provider else None)
                or "Organization Name",
                "url": data_provider.url if data_provider else None,
            },
            "contact": {
                "name": (point_of_contact.name if point_of_contact else None)
                or "Lastname, Firstname",
                "position": (point_of_contact.position if point_of_contact else None)
                or "Position Title",
                "address": (point_of_contact.address if point_of_contact else None)
                or "Mailing Address",
                "city": (point_of_contact.city if point_of_contact else None) or "City",
                "stateorprovince": (
                    point_of_contact.state_or_province if point_of_contact else None
                )
                or "Administrative Area",
                "postalcode": (
                    point_of_contact.postal_code if point_of_contact else None
                )
                or "Zip or Postal Code",
                "country": (point_of_contact.country if point_of_contact else None)
                or "Country",
                "phone": (point_of_contact.phone if point_of_contact else None)
                or "+xx-xxx-xxx-xxxx",
                "fax": (point_of_contact.fax if point_of_contact else None)
                or "+xx-xxx-xxx-xxxx",
                "email": (point_of_contact.email if point_of_contact else None)
                or "you@example.org",
                "url": (point_of_contact.url if point_of_contact else None)
                or "Contact URL",
                "hours": (point_of_contact.contact_hours if point_of_contact else None)
                or "Mo-Fr 08:00-17:00",
                "instructions": (
                    point_of_contact.contact_instructions if point_of_contact else None
                )
                or "During hours of service. Off on weekends.",
                "role": "pointOfContact",
            },
        },
        "resources": {},
    }
    (
        collections,
        total,
    ) = await settings.get_collection_manager().paginated_list_collections(
        user,
        page=collection_page,
        page_size=collection_page_size,
        filter_=CollectionFilter(
            identifiers=[collection_identifier] if collection_identifier else None,
        ),
    )

    for collection in collections:
        pygeoapi_config["resources"][collection.identifier] = (
            _convert_collection_to_pygeoapi_resource(collection, settings)
        )
    # TODO: validate the config
    return pygeoapi_config


def _convert_collection_to_pygeoapi_resource(
    collection: Collection, settings: PottoSettings
) -> dict:
    links = []
    for collection_link in collection.additional_links or []:
        link_ = dict(collection_link)
        type_ = link_.pop("media_type", "")
        links.append({"type": type_, **link_})
    converted_providers = []
    for type_, provider in (collection.providers or {}).items():
        if provider.provider_name == "pygeoapi":
            raw_data = provider.config["data"]
            data = (
                interpolate_configuration_value(raw_data, settings.env_whitelist)
                if isinstance(raw_data, str)
                else raw_data
            )
            converted_providers.append(
                {
                    "type": type_.value,
                    "name": provider.config["python_callable"],
                    "data": data,
                    **provider.config.get("options", {}),
                }
            )

    # NOTE: per-collection custom extents (schemas.collections.Collection has no
    # additional_extents field yet - see the "TODO: Add support for additional
    # extents" marker on that class) are not merged in here.
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
        "providers": converted_providers,
        # owner is not a property recognized by pygeoapi but we require it in
        # potto.Adding it here takes advantage of the fact that pygeoapi
        # allows additional configuration properties on collections
        "owner": collection.owner,
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
