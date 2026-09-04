import logging

from sqlmodel.ext.asyncio.session import AsyncSession

from .....exceptions import PottoException
from .....schemas.metadata import (
    LicenseInformation,
    DataProviderInformation,
    PointOfContact,
    ServerMetadataCreate,
    ServerMetadataFlattenedUpdate,
    ServerMetadataUpdate,
)
from ..models import ServerMetadata
from ..queries.metadata import get_metadata

logger = logging.getLogger(__name__)


async def create_metadata(
    session: AsyncSession, to_create: ServerMetadataCreate
) -> ServerMetadata:
    instance = ServerMetadata.model_validate(to_create.model_dump(exclude_none=True))
    session.add(instance)
    await session.commit()
    await session.refresh(instance)
    if (created := await get_metadata(session)) is None:
        raise PottoException("error creating metadata")
    return created


async def update_metadata(
    session: AsyncSession,
    db_metadata: ServerMetadata,
    to_update: ServerMetadataUpdate,
) -> ServerMetadata:
    for key, value in to_update.model_dump(exclude_unset=True).items():
        setattr(db_metadata, key, value)
    session.add(db_metadata)
    await session.commit()
    await session.refresh(db_metadata)
    return db_metadata


async def update_metadata_flattened(
    session: AsyncSession,
    db_metadata: ServerMetadata,
    to_update: ServerMetadataFlattenedUpdate,
) -> ServerMetadata:
    set_fields = to_update.model_dump(exclude_unset=True)
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
        "title": to_update.title or db_metadata.title,
        "description": to_update.description or db_metadata.description,
        "keywords": to_update.keywords,
    }
    for scalar_field in ("keywords_type", "terms_of_service", "url"):
        if scalar_field in set_fields:
            update_kwargs[scalar_field] = set_fields[scalar_field]
    if unflattened_license:
        update_kwargs["license"] = LicenseInformation(
            name=unflattened_license.get(
                "name", (db_metadata.license or {}).get("name")
            ),
            url=unflattened_license.get("url", (db_metadata.license or {}).get("url")),
        )
    if unflattened_data_provider:
        update_kwargs["data_provider"] = DataProviderInformation(
            name=unflattened_data_provider.get(
                "name", (db_metadata.data_provider or {}).get("name")
            ),
            url=unflattened_data_provider.get(
                "url", (db_metadata.data_provider or {}).get("url")
            ),
        )
    if unflattened_point_of_contact:
        poc = db_metadata.point_of_contact or {}
        update_kwargs["point_of_contact"] = PointOfContact(
            name=unflattened_point_of_contact.get("name", poc.get("name")),
            position=unflattened_point_of_contact.get("position", poc.get("position")),
            address=unflattened_point_of_contact.get("address", poc.get("address")),
            city=unflattened_point_of_contact.get("city", poc.get("city")),
            state_or_province=unflattened_point_of_contact.get(
                "state_or_province", poc.get("state_or_province")
            ),
            postal_code=unflattened_point_of_contact.get(
                "postal_code", poc.get("postal_code")
            ),
            country=unflattened_point_of_contact.get("country", poc.get("country")),
            phone=unflattened_point_of_contact.get("phone", poc.get("phone")),
            fax=unflattened_point_of_contact.get("fax", poc.get("fax")),
            email=unflattened_point_of_contact.get("email", poc.get("email")),
            url=unflattened_point_of_contact.get("url", poc.get("url")),
            contact_hours=unflattened_point_of_contact.get(
                "contact_hours", poc.get("contact_hours")
            ),
            contact_instructions=unflattened_point_of_contact.get(
                "contact_instructions", poc.get("contact_instructions")
            ),
        )
    return await update_metadata(
        session, db_metadata, ServerMetadataUpdate.model_validate(update_kwargs)
    )


async def delete_metadata(
    session: AsyncSession,
) -> None:
    if instance := (await get_metadata(session)):
        await session.delete(instance)
        await session.commit()
    else:
        raise PottoException("Server metadata not found.")
