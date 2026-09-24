"""Permission-checked business logic backing ``PostgisManager``.

The functions defined in this module always return instances of potto's public,
storage-agnostic schemas (``potto.schemas.*``), never this package's private ORM
models.
"""

import logging

from sqlmodel.ext.asyncio.session import AsyncSession

from ....authz.authorizer import (
    PottoAuthorizer,
    Principal,
)
from ....exceptions import PottoCannotEditServerMetadataException
from ....schemas.metadata import (
    ServerMetadata,
    ServerMetadataCreate,
    ServerMetadataUpdate,
)
from ..db.commands import metadata as metadata_commands
from ..db.queries.metadata import get_metadata

logger = logging.getLogger(__name__)


async def get_server_metadata(session: AsyncSession) -> ServerMetadata:
    """Return pre-existing server metadata, creating a default record if none exists."""
    if existing := await get_metadata(session):
        return existing.to_potto()
    created = await metadata_commands.create_metadata(
        session, ServerMetadataCreate(title="Default title")
    )
    return created.to_potto()


async def update_server_metadata(
    session: AsyncSession,
    user: Principal | None,
    authorizer: PottoAuthorizer,
    to_update: ServerMetadataUpdate,
) -> ServerMetadata:
    if not await authorizer.can_edit_server_metadata(user):
        raise PottoCannotEditServerMetadataException(
            "User does not have permission to edit server metadata."
        )
    db_metadata = await get_metadata(session)
    if db_metadata is None:
        db_metadata = await metadata_commands.create_metadata(
            session, ServerMetadataCreate(title="Default title")
        )
    updated = await metadata_commands.update_metadata(session, db_metadata, to_update)
    return updated.to_potto()
