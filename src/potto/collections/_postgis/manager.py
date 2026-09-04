from potto.authz.base import AuthorizationBackendProtocol
import asyncio
from typing import (
    Any,
    cast,
    Literal,
)

import alembic.config
import pydantic
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from pydantic.networks import PostgresDsn
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio.engine import (
    AsyncEngine,
    create_async_engine,
)
from sqlalchemy.ext.asyncio.session import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette_admin.contrib.sqlmodel import ModelView

from ...config import PottoSettings
from ...schemas.auth import PottoUser
from ...schemas.collections import (
    Collection,
    CollectionCreate,
    CollectionUpdate,
)
from ..protocols import (
    CollectionFilter,
    CollectionManagerCapabilities,
    CollectionManagerProtocol,
)
from . import operations
from .admin_webui import CollectionView
from .db.alembic_utils import build_alembic_config


class PostgisCollectionManagerConfiguration(pydantic.BaseModel):
    _db_engine: AsyncEngine | None = None
    _db_session_maker: async_sessionmaker | None = None

    database_dsn: PostgresDsn = PostgresDsn(
        "postgresql+psycopg://potto:pottopass@localhost/potto"
    )

    def get_db_engine(self) -> AsyncEngine:
        if self._db_engine is None:
            self._db_engine = create_async_engine(self.database_dsn.unicode_string())
        return self._db_engine

    def get_db_session_maker(self) -> async_sessionmaker:
        if self._db_session_maker is None:
            self._db_session_maker = async_sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.get_db_engine(),
                expire_on_commit=False,
                class_=AsyncSession,
            )
        return self._db_session_maker


class PostgisCollectionManager:
    """A potto collection manager backed by a PostGIS DB."""
    authorization_backend: AuthorizationBackendProtocol
    config: PostgisCollectionManagerConfiguration
    settings: PottoSettings

    def __init__(self, config: PostgisCollectionManagerConfiguration, settings: PottoSettings):
        self.authorization_backend = settings.get_authorization_backend()
        self.config = config
        self.settings = settings

    async def check_health(self) -> Literal["ok", "not-ready", "error"]:
        """Check whether the manager is healthy."""
        return await _check_health(
            build_alembic_config(self.config.database_dsn.unicode_string())
        )

    async def set_up(self) -> bool:
        """Ensure the manager is ready to be used by potto."""
        raise NotImplementedError

    async def get_starlette_admin_view(self) -> "type[ModelView] | None":
        """Return a starlette_admin view suitable for using the in potto admin ui."""
        return CollectionView

    async def get_capabilities(self) -> CollectionManagerCapabilities:
        return CollectionManagerCapabilities(
            supports_creation=True,
            supports_modification=True,
            supports_deletion=True,
            supports_granting_access=True,
            supports_revoking_access=True,
        )
    
    async def get_collection(
            self,
            identifier: str,
            user: PottoUser | None,
    ) -> Collection | None:
        """Retrieve a collection."""
        async with self.config.get_db_session_maker()() as db_session:
            return await operations.get_collection_by_resource_identifier(
                db_session,
                user,
                self.authorization_backend,
                identifier
            )

    async def paginated_list_collections(
            self,
            user: PottoUser | None,
            *,
            page: int = 1,
            page_size: int = 20,
            include_total: bool = False,
            filter_: CollectionFilter | None = None,
    ) -> tuple[list[Collection], int | None]:
        """Retrieve a list of collections"""
        async with self.config.get_db_session_maker()() as db_session:
            return await operations.paginated_list_collections(
                db_session,
                user,
                self.authorization_backend,
                page=page,
                page_size=page_size,
                include_total=include_total,
            )

    async def create_collection(
            self,
            to_create: CollectionCreate,
            user: PottoUser,
    ) -> Collection:
        """Create a new collection."""
        async with self.config.get_db_session_maker()() as db_session:
            return await operations.create_collection(
                db_session,
                user,
                self.authorization_backend,
                to_create,
                self.settings
            )

    async def update_collection(
            self,
            collection: Collection,
            to_update: CollectionUpdate,
            user: PottoUser,
    ) -> Collection:
        """Update an existing collection.

        When the manager does not support updating collections this should raise
        ``potto.collections.exceptions.CollectionManagerCapabilityNotSupported``.
        """
        async with self.config.get_db_session_maker()() as db_session:
            return await operations.update_collection(
                db_session,
                user,
                self.authorization_backend,
                collection,
                to_update
            )

    async def delete_collection(
            self,
            identifier: str,
            user: PottoUser,
    ) -> None:
        """Delete a collection."""
        async with self.config.get_db_session_maker()() as db_session:
            return await operations.delete_collection(
                db_session,
                user,
                self.authorization_backend,
                identifier
            )

    async def grant_collection_access(
            self,
            *,
            granting_user: PottoUser,
            target_user_id: str,
            collection: Collection,
            role: str,
    ) -> None:
        """Grant a role on the input collection to the target user.

        When the manager does not support granting collection access this should raise
        ``potto.collections.exceptions.CollectionManagerCapabilityNotSupported``.
        """
        async with self.config.get_db_session_maker()() as db_session:
            return await operations.grant_collection_access(
                db_session,
                granting_user,
                self.authorization_backend,
                target_user_id,
                collection,
                role
            )

    async def revoke_collection_access(
            self,
            *,
            revoking_user: PottoUser,
            target_user_id: str,
            collection: Collection,
    ) -> None:
        """Revoke a user's access to a collection.

        When the manager does not support revoking collection access this should raise
        ``potto.collections.exceptions.CollectionManagerCapabilityNotSupported``.
        """
        async with self.config.get_db_session_maker()() as db_session:
            return await operations.revoke_collection_access(
                db_session, revoking_user, self.authorization_backend,
                target_user_id,
                collection,
            )


def get_collection_manager(
    raw_config: dict[str, Any],
    settings: PottoSettings,
) -> CollectionManagerProtocol:
    config = PostgisCollectionManagerConfiguration.model_validate(raw_config)
    return PostgisCollectionManager(config, settings)


def _get_current_and_head_revisions(
    alembic_config: alembic.config.Config,
) -> tuple[set[str], set[str]]:
    script = ScriptDirectory.from_config(alembic_config)
    head_revisions = set(script.get_heads())
    # always set by build_alembic_config(), the only place that constructs
    # an alembic_config for this function
    db_url = cast(str, alembic_config.get_main_option("sqlalchemy.url"))
    engine = create_engine(db_url)
    try:
        with engine.connect() as connection:
            current_revisions = set(
                MigrationContext.configure(connection).get_current_heads()
            )
    finally:
        engine.dispose()
    return current_revisions, head_revisions


async def _check_health(alembic_config: alembic.config.Config) -> Literal["ok", "not-ready", "error"]:
    """Check DB connectivity and whether it's stamped at the migrations head.

    Connects to the DB and compares its current alembic revision(s) against
    the migration scripts' head - this catches both an unreachable DB and one
    that's behind on migrations, without a separate connectivity check.

    Deliberately avoids alembic's autogenerate (e.g. ``alembic.command.check``,
    used by the CLI's ``check_for_changes``): autogenerate's diffing mutates
    shared SQLAlchemy metadata for enum-typed columns as a side effect (a bug
    in ``alembic_postgresql_enum``'s autogenerate hook, which reassigns
    ``column.type`` in place on the actual mapped ``Table`` objects rather
    than a copy, whenever it has to render a ``CreateTableOp``/``AddColumnOp``
    for one). That's tolerable for a one-off CLI command, but this check runs
    against a live, long-running server process - the first time it observes
    a missing/outdated table it would permanently corrupt that column's
    ``enum_class`` for the rest of the process's life (breaking, e.g., the
    admin UI's ``CollectionView``). A plain revision-vs-head comparison never
    touches autogenerate at all, so it can't trigger that bug - the trade-off
    is that it won't catch a DB that's stamped at head but whose live schema
    was hand-edited to no longer match the models.
    """
    try:
        current_revisions, head_revisions = await asyncio.to_thread(
            _get_current_and_head_revisions, alembic_config
        )
    except Exception:
        return "error"

    if current_revisions == head_revisions:
        return "ok"
    return "not-ready"
