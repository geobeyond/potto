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
