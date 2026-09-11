import dataclasses
import logging

import pydantic

from .base import (
    Title,
    MaybeDescription,
    MaybeKeywords,
)

logger = logging.getLogger(__name__)


class PointOfContact(pydantic.BaseModel):
    name: str | None = None
    position: str | None = None
    address: str | None = None
    city: str | None = None
    state_or_province: str | None = None
    postal_code: str | None = None
    country: str | None = None
    phone: str | None = None
    fax: str | None = None
    email: str | None = None
    url: str | None = None
    contact_hours: str | None = None
    contact_instructions: str | None = None


class LicenseInformation(pydantic.BaseModel):
    name: str
    url: str | None = None


class DataProviderInformation(pydantic.BaseModel):
    name: str
    url: str | None = None


class ServerMetadataCreate(pydantic.BaseModel):
    title: Title
    description: MaybeDescription = None
    keywords: MaybeKeywords = None
    license: LicenseInformation | None = None
    data_provider: DataProviderInformation | None = None
    point_of_contact: PointOfContact | None = None


class ServerMetadataUpdate(pydantic.BaseModel):
    title: Title | None = None
    description: MaybeDescription = None
    keywords: MaybeKeywords = None
    keywords_type: str | None = None
    terms_of_service: MaybeDescription = None
    url: str | None = None
    license: LicenseInformation | None = None
    data_provider: DataProviderInformation | None = None
    point_of_contact: PointOfContact | None = None


class ServerMetadataFlattenedUpdate(pydantic.BaseModel):
    title: str | None = None
    description: str | None = None
    keywords: MaybeKeywords = None
    keywords_type: str | None = None
    terms_of_service: MaybeDescription = None
    url: str | None = None
    license_name: str | None = None
    license_url: str | None = None
    data_provider_name: str | None = None
    data_provider_url: str | None = None
    point_of_contact_name: str | None = None
    point_of_contact_position: str | None = None
    point_of_contact_address: str | None = None
    point_of_contact_city: str | None = None
    point_of_contact_state_or_province: str | None = None
    point_of_contact_postal_code: str | None = None
    point_of_contact_country: str | None = None
    point_of_contact_phone: str | None = None
    point_of_contact_fax: str | None = None
    point_of_contact_email: str | None = None
    point_of_contact_url: str | None = None
    point_of_contact_contact_hours: str | None = None
    point_of_contact_contact_instructions: str | None = None


@dataclasses.dataclass(frozen=True)
class ServerMetadata:
    title: Title
    description: MaybeDescription = None
    keywords: MaybeKeywords = None
    keywords_type: str | None = None
    terms_of_service: MaybeDescription = None
    url: str | None = None
    license: LicenseInformation | None = None
    data_provider: DataProviderInformation | None = None
    point_of_contact: PointOfContact | None = None


def unflatten_server_metadata_update(
    existing: ServerMetadata,
    flattened: ServerMetadataFlattenedUpdate,
) -> ServerMetadataUpdate:
    """Merge a flat, CLI-friendly update onto existing metadata's nested shape."""
    set_fields = flattened.model_dump(exclude_unset=True)
    unflattened_license = {}
    unflattened_data_provider = {}
    unflattened_point_of_contact = {}
    for key, value in set_fields.items():
        if key.startswith("license_"):
            unflattened_license[key[len("license_") :]] = value
        elif key.startswith("data_provider_"):
            unflattened_data_provider[key[len("data_provider_") :]] = value
        elif key.startswith("point_of_contact_"):
            unflattened_point_of_contact[key[len("point_of_contact_") :]] = value

    update_kwargs: dict = {
        "title": flattened.title or existing.title,
        "description": flattened.description or existing.description,
        "keywords": flattened.keywords,
    }
    for scalar_field in ("keywords_type", "terms_of_service", "url"):
        if scalar_field in set_fields:
            update_kwargs[scalar_field] = set_fields[scalar_field]

    existing_license = existing.license
    if unflattened_license:
        update_kwargs["license"] = LicenseInformation(
            name=unflattened_license.get(
                "name", existing_license.name if existing_license else None
            ),
            url=unflattened_license.get(
                "url", existing_license.url if existing_license else None
            ),
        )
    existing_data_provider = existing.data_provider
    if unflattened_data_provider:
        update_kwargs["data_provider"] = DataProviderInformation(
            name=unflattened_data_provider.get(
                "name",
                existing_data_provider.name if existing_data_provider else None,
            ),
            url=unflattened_data_provider.get(
                "url", existing_data_provider.url if existing_data_provider else None
            ),
        )
    existing_poc = existing.point_of_contact
    if unflattened_point_of_contact:

        def _poc(field: str) -> str | None:
            return unflattened_point_of_contact.get(
                field, getattr(existing_poc, field) if existing_poc else None
            )

        update_kwargs["point_of_contact"] = PointOfContact(
            name=_poc("name"),
            position=_poc("position"),
            address=_poc("address"),
            city=_poc("city"),
            state_or_province=_poc("state_or_province"),
            postal_code=_poc("postal_code"),
            country=_poc("country"),
            phone=_poc("phone"),
            fax=_poc("fax"),
            email=_poc("email"),
            url=_poc("url"),
            contact_hours=_poc("contact_hours"),
            contact_instructions=_poc("contact_instructions"),
        )
    return ServerMetadataUpdate.model_validate(update_kwargs)


@dataclasses.dataclass(frozen=True)
class ServerMetadataManagerCapabilities:
    supports_modification: bool = False
