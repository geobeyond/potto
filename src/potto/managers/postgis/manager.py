import asyncio
from typing import (
    Any,
    cast,
    Literal,
    TYPE_CHECKING,
)

import alembic.config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from ...authz.protocols import AuthorizationBackendProtocol
from ...schemas import (
    auth as auth_schemas,
    collections as collection_schemas,
    metadata as metadata_schemas,
    processes as process_schemas,
)

from .operations import (
    collections as collection_ops,
    metadata as metadata_ops,
    processes as process_ops,
    users as user_ops,
)
from .admin.collections import CollectionView
from .admin.metadata import ServerMetadataModelView
from .admin.users import UserView
from .config import PostgisManagerConfiguration
from .db.alembic_utils import build_alembic_config

if TYPE_CHECKING:
    import cyclopts
    from starlette_admin.views import BaseModelView

    from ...config import PottoSettings


class PostgisManager:
    """A potto manager backed by a PostGIS DB.

    This implements the following potto manager protocols:

    - ``CollectionManagerProtocol``,
    - ``ProcessManagerProtocol``,
    - ``ServerMetadataProtocol``
    """

    authorization_backend: AuthorizationBackendProtocol
    config: PostgisManagerConfiguration
    settings: "PottoSettings"

    def __init__(self, config: PostgisManagerConfiguration, settings: "PottoSettings"):
        self.authorization_backend = settings.get_authorization_backend()
        self.config = config
        self.settings = settings

    async def check_health(self) -> Literal["ok", "not-ready", "error"]:
        """Check whether the manager is healthy."""
        return await _check_health(
            build_alembic_config(self.config.database_dsn.unicode_string())
        )

    @property
    def potto_cli_group(self) -> str:
        return "postgis-manager"

    async def get_cli_group(self) -> "cyclopts.App | None":
        from .cli import build_cli_group

        return build_cli_group(self)

    async def get_collection_admin_view(self) -> "BaseModelView | None":
        return CollectionView()

    async def get_collection_capabilities(
        self,
    ) -> collection_schemas.CollectionManagerCapabilities:
        return collection_schemas.CollectionManagerCapabilities(
            supports_creation=True,
            supports_modification=True,
            supports_deletion=True,
            supports_granting_access=True,
            supports_revoking_access=True,
        )

    async def get_collection(
        self,
        identifier: str,
        user: auth_schemas.PottoUser | None,
    ) -> collection_schemas.Collection | None:
        """Retrieve a collection."""
        async with self.config.get_db_session_maker()() as db_session:
            return await collection_ops.get_collection_by_resource_identifier(
                db_session, user, self.authorization_backend, identifier
            )

    async def paginated_list_collections(
        self,
        user: auth_schemas.PottoUser | None,
        *,
        page: int = 1,
        page_size: int = 20,
        include_total: bool = False,
        filter_: collection_schemas.CollectionFilter | None = None,
    ) -> tuple[list[collection_schemas.Collection], int | None]:
        """Retrieve a list of collections"""
        async with self.config.get_db_session_maker()() as db_session:
            return await collection_ops.paginated_list_collections(
                db_session,
                user,
                self.authorization_backend,
                page=page,
                page_size=page_size,
                include_total=include_total,
                identifier_filter=(
                    filter_.identifiers[0]
                    if filter_ is not None and filter_.identifiers
                    else None
                ),
                collection_type_filter=(
                    [filter_.type_] if filter_ is not None and filter_.type_ else None
                ),
                spatial_intersect=(
                    filter_.spatial_intersect if filter_ is not None else None
                ),
            )

    async def create_collection(
        self,
        to_create: collection_schemas.CollectionCreate,
        user: auth_schemas.PottoUser,
    ) -> collection_schemas.Collection:
        """Create a new collection."""
        async with self.config.get_db_session_maker()() as db_session:
            return await collection_ops.create_collection(
                db_session, user, self.authorization_backend, to_create, self.settings
            )

    async def update_collection(
        self,
        collection: collection_schemas.Collection,
        to_update: collection_schemas.CollectionUpdate,
        user: auth_schemas.PottoUser,
    ) -> collection_schemas.Collection:
        """Update an existing collection."""
        async with self.config.get_db_session_maker()() as db_session:
            return await collection_ops.update_collection(
                db_session, user, self.authorization_backend, collection, to_update
            )

    async def delete_collection(
        self,
        identifier: str,
        user: auth_schemas.PottoUser,
    ) -> None:
        """Delete a collection."""
        async with self.config.get_db_session_maker()() as db_session:
            return await collection_ops.delete_collection(
                db_session, user, self.authorization_backend, identifier
            )

    async def grant_collection_access(
        self,
        *,
        granting_user: auth_schemas.PottoUser,
        target_user_id: str,
        collection: collection_schemas.Collection,
        role: str,
    ) -> None:
        """Grant a role on the input collection to the target user."""
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.grant_collection_access(
                db_session,
                granting_user,
                self.authorization_backend,
                target_user_id,
                collection,
                role,
            )

    async def revoke_collection_access(
        self,
        *,
        revoking_user: auth_schemas.PottoUser,
        target_user_id: str,
        collection: collection_schemas.Collection,
    ) -> None:
        """Revoke a user's access to a collection."""
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.revoke_collection_access(
                db_session,
                revoking_user,
                self.authorization_backend,
                target_user_id,
                collection,
            )

    async def get_server_metadata_admin_view(self) -> "BaseModelView | None":
        return ServerMetadataModelView()

    async def get_server_metadata_capabilities(
        self,
    ) -> metadata_schemas.ServerMetadataManagerCapabilities:
        return metadata_schemas.ServerMetadataManagerCapabilities(
            supports_modification=True
        )

    async def get_server_metadata(self) -> metadata_schemas.ServerMetadata:
        async with self.config.get_db_session_maker()() as db_session:
            return await metadata_ops.get_server_metadata(db_session)

    async def update_server_metadata(
        self,
        to_update: metadata_schemas.ServerMetadataUpdate,
        user: auth_schemas.PottoUser | None,
    ) -> metadata_schemas.ServerMetadata:
        async with self.config.get_db_session_maker()() as db_session:
            return await metadata_ops.update_server_metadata(
                db_session,
                user,
                self.authorization_backend,
                to_update,
            )

    async def get_user_account_admin_view(self) -> "BaseModelView | None":
        return UserView()

    async def get_user_account_capabilities(
        self,
    ) -> auth_schemas.UserAccountManagerCapabilities:
        return auth_schemas.UserAccountManagerCapabilities(
            supports_creation=True,
            supports_modification=True,
            supports_deletion=True,
        )

    async def get_user(
        self,
        user_id: str,
        requesting_user: auth_schemas.PottoUser | None,
    ) -> auth_schemas.PottoUser | None:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.get_user(
                db_session, requesting_user, self.authorization_backend, user_id
            )

    async def get_user_by_username(
        self,
        username: str,
        requesting_user: auth_schemas.PottoUser | None,
    ) -> auth_schemas.PottoUser | None:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.get_user_by_username(
                db_session, requesting_user, self.authorization_backend, username
            )

    async def paginated_list_users(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        include_total: bool = False,
        filter_: auth_schemas.UserFilter | None = None,
        requesting_user: auth_schemas.PottoUser | None,
    ) -> tuple[list[auth_schemas.PottoUser], int | None]:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.paginated_list_users(
                db_session,
                requesting_user,
                self.authorization_backend,
                username_filter=filter_.username if filter_ else None,
                admin_filter=bool(filter_ and filter_.is_admin),
                page=page,
                page_size=page_size,
                include_total=include_total,
            )

    async def create_user(
        self,
        to_create: auth_schemas.UserCreate,
        requesting_user: auth_schemas.PottoUser | None,
    ) -> auth_schemas.PottoUser:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.create_user(
                db_session,
                requesting_user,
                self.authorization_backend,
                to_create,
            )

    async def update_user(
        self,
        user_id: str,
        to_update: auth_schemas.UserUpdate,
        requesting_user: auth_schemas.PottoUser | None,
    ) -> auth_schemas.PottoUser:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.update_user(
                db_session,
                requesting_user,
                self.authorization_backend,
                user_id,
                to_update,
            )

    async def delete_user(
        self,
        user_id: str,
        requesting_user: auth_schemas.PottoUser | None,
    ) -> None:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.delete_user(
                db_session, requesting_user, self.authorization_backend, user_id
            )

    async def provision_oidc_user(
        self, to_create: auth_schemas.UserCreateFromOidc
    ) -> auth_schemas.PottoUser:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.provision_oidc_user(db_session, to_create)

    async def authenticate(
        self, username: str, password: str
    ) -> auth_schemas.PottoUser | None:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.authenticate(db_session, username, password)

    async def list_resource_editors(
        self,
        resource_type: str,
        resource_identifier: str,
        requesting_user: auth_schemas.PottoUser | None,
    ) -> list[auth_schemas.PottoUser]:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.list_resource_editors(
                db_session,
                requesting_user,
                self.authorization_backend,
                resource_type,
                resource_identifier,
            )

    async def list_resource_viewers(
        self,
        resource_type: str,
        resource_identifier: str,
        requesting_user: auth_schemas.PottoUser | None,
    ) -> list[auth_schemas.PottoUser]:
        async with self.config.get_db_session_maker()() as db_session:
            return await user_ops.list_resource_viewers(
                db_session,
                requesting_user,
                self.authorization_backend,
                resource_type,
                resource_identifier,
            )

    async def get_process_admin_view(self) -> BaseModelView | None:
        raise NotImplementedError

    async def get_process_capabilities(
        self,
    ) -> process_schemas.ProcessManagerCapabilities:
        return process_schemas.ProcessManagerCapabilities(
            supports_creation=True,
            supports_modification=True,
            supports_deletion=True,
            supports_granting_access=True,
            supports_revoking_access=True,
        )

    async def get_process(
        self,
        identifier: str,
        user: auth_schemas.PottoUser | None,
    ) -> process_schemas.Process | None:
        raise NotImplementedError

    async def paginated_list_processes(
        self,
        user: auth_schemas.PottoUser | None,
        *,
        page: int = 1,
        page_size: int = 20,
        include_total: bool = False,
        filter_: process_schemas.ProcessFilter | None = None,
    ) -> tuple[list[process_schemas.Process], int | None]:
        raise NotImplementedError

    async def create_process(
        self,
        to_create: process_schemas.ProcessCreate,
        user: auth_schemas.PottoUser,
    ) -> process_schemas.Process:
        """Create a new process.

        When the manager does not support creating processes this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """
        raise NotImplementedError

    async def update_process(
        self,
        process: process_schemas.Process,
        to_update: process_schemas.ProcessUpdate,
        user: auth_schemas.PottoUser,
    ) -> process_schemas.Process:
        """Update an existing process.

        When the manager does not support updating processes this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """
        raise NotImplementedError

    async def delete_process(
        self,
        identifier: str,
        user: auth_schemas.PottoUser,
    ) -> None:
        """Delete a process.

        When the manager does not support deleting processes this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """
        raise NotImplementedError

    async def grant_process_access(
        self,
        *,
        granting_user: auth_schemas.PottoUser,
        target_user_id: str,
        process: process_schemas.Process,
        role: str,
    ) -> None:
        """Grant a role on the input process to the target user.

        When the manager does not support granting process access this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """
        raise NotImplementedError

    async def revoke_process_access(
        self,
        *,
        revoking_user: auth_schemas.PottoUser,
        target_user_id: str,
        process: process_schemas.Process,
    ) -> None:
        """Revoke a user's access to a process.

        When the manager does not support revoking process access this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """
        raise NotImplementedError

    async def deploy_process(
        self,
        process: process_schemas.Process,
        to_deploy: process_schemas.ProcessDeploymentCreate,
        user: auth_schemas.PottoUser,
    ) -> process_schemas.ProcessDeployment:
        """(Re)deploy a process.

        When the manager does not support deploying processes this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """
        raise NotImplementedError

    async def undeploy_process(
        self,
        identifier: str,
        user: auth_schemas.PottoUser,
    ) -> None:
        """Undeploy a process.

        When the manager does not support deploying processes this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """
        raise NotImplementedError


_manager_cache: dict[str, PostgisManager] = {}


def get_postgis_manager(
    raw_config: dict[str, Any],
    settings: "PottoSettings",
) -> PostgisManager:
    # PostgisManager implements all three ...Protocol types, so this one factory
    # satisfies CollectionManagerFactoryProtocol/ServerMetadataManagerFactoryProtocol/
    # UserAccountManagerFactoryProtocol at once - no separate wrapper per protocol needed.
    config = PostgisManagerConfiguration.model_validate(raw_config)
    key = config.database_dsn.unicode_string()
    if key not in _manager_cache:
        _manager_cache[key] = PostgisManager(config, settings)
    return _manager_cache[key]


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


async def _check_health(
    alembic_config: alembic.config.Config,
) -> Literal["ok", "not-ready", "error"]:
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
