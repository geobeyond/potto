import tomllib
from pathlib import Path
from typing import (
    Any,
    Literal,
    TYPE_CHECKING,
)

import bcrypt
import pydantic
import shapely

from ...authz.protocols import AuthorizationBackendProtocol
from ...exceptions import (
    CapabilityNotSupported,
    PottoCannotViewUserException,
)
from ...schemas.auth import (
    PottoScope,
    PottoUser,
    UserFilter,
    UserAccountManagerCapabilities,
)
from ...schemas.collections import (
    Collection,
    CollectionFilter,
    CollectionManagerCapabilities,
)
from ...schemas.metadata import ServerMetadata, ServerMetadataManagerCapabilities
from . import parsing

if TYPE_CHECKING:
    import cyclopts
    from starlette_admin.views import BaseModelView

    from ...config import PottoSettings
    from ...schemas.auth import UserCreate, UserCreateFromOidc, UserUpdate
    from ...schemas.collections import (
        CollectionCreate,
        CollectionUpdate,
    )
    from ...schemas.metadata import ServerMetadataUpdate


def _paginate(items: list, page: int, page_size: int) -> list:
    offset = page_size * (page - 1)
    return items[offset : offset + page_size]


class ConfigurationFileManagerConfiguration(pydantic.BaseModel):
    config_file: Path


class ConfigurationFileManager:
    """A potto manager that uses a configuration file as its store.

    Read-only: the config file is parsed once, at construction time, and everything
    else is served out of memory.

    Implements the following potto protocols:

    - CollectionManagerProtocol
    - ServerMetadataManagerProtocol
    - UserAccountManagerProtocol
    """

    authorization_backend: AuthorizationBackendProtocol
    config: ConfigurationFileManagerConfiguration
    collections: dict[str, Collection]
    server_metadata: ServerMetadata
    user_accounts: dict[str, PottoUser]
    _hashed_passwords: dict[str, str]

    def __init__(
        self,
        config: ConfigurationFileManagerConfiguration,
        authorization_backend: AuthorizationBackendProtocol,
    ) -> None:
        self.authorization_backend = authorization_backend
        self.config = config
        raw_configuration = tomllib.loads(config.config_file.read_text())
        self.user_accounts, self._hashed_passwords = parsing.parse_user_accounts(
            raw_configuration.get("user_account", [])
        )
        self.collections = parsing.parse_collections(
            raw_configuration.get("collection", []), self.user_accounts
        )
        self.server_metadata = parsing.parse_server_metadata(
            raw_configuration.get("server_metadata", {})
        )

    async def check_health(self) -> Literal["ok", "not-ready", "error"]:
        """Check whether the manager is healthy."""
        return "ok" if self.config.config_file.is_file() else "error"

    @property
    def potto_cli_group(self) -> str:
        return "configuration-file-manager"

    async def get_cli_group(self) -> "cyclopts.App | None":
        return None

    # --- collections ---------------------------------------------------------

    async def get_collection_admin_view(self) -> "BaseModelView | None":
        """Return a starlette_admin view suitable for use in potto's admin ui."""
        from .admin.collections import CollectionView

        return CollectionView()

    async def get_collection_capabilities(self) -> CollectionManagerCapabilities:
        """Return the manager's capabilities."""
        return CollectionManagerCapabilities()

    async def get_collection(
        self,
        identifier: str,
        user: "PottoUser | None",
    ) -> Collection | None:
        """Retrieve a collection."""
        if (collection := self.collections.get(identifier)) is None:
            return None
        if await self.authorization_backend.can_view_collection(user, collection):
            return collection
        else:
            return None

    async def paginated_list_collections(
        self,
        user: "PottoUser | None",
        *,
        page: int = 1,
        page_size: int = 20,
        include_total: bool = False,
        filter_: CollectionFilter | None = None,
    ) -> tuple[list[Collection], int | None]:
        """Retrieve a list of collections"""
        candidates = sorted(self.collections.values(), key=lambda c: c.identifier)
        if filter_ is not None:
            if filter_.identifiers:
                identifiers = set(filter_.identifiers)
                candidates = [c for c in candidates if c.identifier in identifiers]
            if filter_.type_ is not None:
                candidates = [c for c in candidates if c.type_ == filter_.type_]
            if filter_.spatial_intersect is not None:
                # A collection with no spatial_extent is treated as unbounded and
                # always matches, mirroring PostgisManager's equivalent query
                # (`Collection.spatial_extent.is_(None)` in its OR clause).
                candidates = [
                    c
                    for c in candidates
                    if c.spatial_extent is None
                    or shapely.intersects(c.spatial_extent, filter_.spatial_intersect)
                ]
        accessible = [
            c
            for c in candidates
            if await self.authorization_backend.can_view_collection(user, c)
        ]
        total = len(accessible) if include_total else None
        return _paginate(accessible, page, page_size), total

    async def create_collection(
        self,
        to_create: "CollectionCreate",
        user: "PottoUser",
    ) -> "Collection":
        """Create a new collection.

        When the manager does not support creating collections this should raise
        ``CapabilityNotSupported``.
        """
        raise CapabilityNotSupported(
            "Creating collections is not supported by the configuration file manager."
        )

    async def update_collection(
        self,
        collection: "Collection",
        to_update: "CollectionUpdate",
        user: "PottoUser",
    ) -> "Collection":
        """Update an existing collection.

        When the manager does not support updating collections this should raise
        ``CapabilityNotSupported``.
        """
        raise CapabilityNotSupported(
            "Updating collections is not supported by the configuration file manager."
        )

    async def delete_collection(
        self,
        identifier: str,
        user: "PottoUser",
    ) -> None:
        """Delete a collection.

        When the manager does not support deleting collections this should raise
        ``CapabilityNotSupported``.
        """
        raise CapabilityNotSupported(
            "Deleting collections is not supported by the configuration file manager."
        )

    async def grant_collection_access(
        self,
        *,
        granting_user: "PottoUser",
        target_user_id: str,
        collection: "Collection",
        role: str,
    ) -> None:
        """Grant a role on the input collection to the target user.

        When the manager does not support granting collection access this should raise
        ``CapabilityNotSupported``.
        """
        raise CapabilityNotSupported(
            "Granting collection access is not supported by the "
            "configuration file manager."
        )

    async def revoke_collection_access(
        self,
        *,
        revoking_user: "PottoUser",
        target_user_id: str,
        collection: "Collection",
    ) -> None:
        """Revoke a user's access to a collection.

        When the manager does not support revoking collection access this should raise
        ``CapabilityNotSupported``.
        """
        raise CapabilityNotSupported(
            "Revoking collection access is not supported by the configuration file manager."
        )

    # --- server metadata -------------------------------------------------------

    async def get_server_metadata_admin_view(self) -> "BaseModelView | None":
        """Return a starlette_admin view suitable for use in potto's admin ui."""
        from .admin.metadata import ServerMetadataModelView

        return ServerMetadataModelView()

    async def get_server_metadata_capabilities(
        self,
    ) -> ServerMetadataManagerCapabilities:
        """Return the manager's capabilities."""
        return ServerMetadataManagerCapabilities()

    async def get_server_metadata(self) -> ServerMetadata:
        """Return pre-existing server metadata, creating a default record if none exists."""
        return self.server_metadata

    async def update_server_metadata(
        self,
        to_update: "ServerMetadataUpdate",
        user: PottoUser | None,
    ) -> ServerMetadata:
        """Update the server's metadata.

        When the manager does not support updating metadata this should raise
        ``CapabilityNotSupported``.
        """
        raise CapabilityNotSupported(
            "Updating server metadata is not supported by the configuration file manager."
        )

    # --- user accounts -----------------------------------------------------------

    async def get_user_account_admin_view(self) -> "BaseModelView | None":
        """Return a starlette_admin view suitable for use in potto's admin ui."""
        from .admin.users import UserView

        return UserView()

    async def get_user_account_capabilities(self) -> UserAccountManagerCapabilities:
        """Return the manager's capabilities."""
        return UserAccountManagerCapabilities()

    async def get_user(
        self,
        user_id: str,
        requesting_user: PottoUser | None,
    ) -> PottoUser | None:
        """Retrieve a user by id."""
        if not await self.authorization_backend.can_view_user(requesting_user):
            raise PottoCannotViewUserException(
                "User does not have permission to view user accounts."
            )
        return self.user_accounts.get(user_id)

    async def get_user_by_username(
        self,
        username: str,
        requesting_user: PottoUser | None,
    ) -> PottoUser | None:
        """Retrieve a user by username."""
        if not await self.authorization_backend.can_view_user(requesting_user):
            raise PottoCannotViewUserException(
                "User does not have permission to view user accounts."
            )
        for user in self.user_accounts.values():
            if user.username == username:
                return user
        return None

    async def paginated_list_users(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        include_total: bool = False,
        filter_: UserFilter | None = None,
        requesting_user: PottoUser | None,
    ) -> tuple[list[PottoUser], int | None]:
        """Retrieve a list of users."""
        if not await self.authorization_backend.can_view_user(requesting_user):
            raise PottoCannotViewUserException(
                "User does not have permission to view user accounts."
            )
        candidates = sorted(self.user_accounts.values(), key=lambda u: u.username)
        if filter_ is not None:
            if filter_.username:
                needle = filter_.username.lower()
                candidates = [u for u in candidates if needle in u.username.lower()]
            if filter_.is_admin:
                candidates = [
                    u for u in candidates if PottoScope.ADMIN.value in u.scopes
                ]
        total = len(candidates) if include_total else None
        return _paginate(candidates, page, page_size), total

    async def create_user(
        self,
        to_create: "UserCreate",
        requesting_user: "PottoUser | None",
    ) -> "PottoUser":
        """Create a new local user.

        When the manager does not support creating users this should raise
        ``CapabilityNotSupported``.
        """
        raise CapabilityNotSupported(
            "Creating users is not supported by the configuration file manager."
        )

    async def update_user(
        self,
        user_id: str,
        to_update: "UserUpdate",
        requesting_user: "PottoUser | None",
    ) -> "PottoUser":
        """Update an existing user.

        When the manager does not support updating users this should raise
        ``CapabilityNotSupported``.
        """
        raise CapabilityNotSupported(
            "Updating users is not supported by the configuration file manager."
        )

    async def delete_user(
        self,
        user_id: str,
        requesting_user: "PottoUser | None",
    ) -> None:
        """Delete a user.

        When the manager does not support deleting users this should raise
        ``CapabilityNotSupported``.
        """
        raise CapabilityNotSupported(
            "Deleting users is not supported by the configuration file manager."
        )

    async def provision_oidc_user(self, to_create: "UserCreateFromOidc") -> "PottoUser":
        """Just-in-time provision a user from an OIDC identity provider."""
        raise CapabilityNotSupported(
            "Provisioning users from an OIDC identity provider is not supported by "
            "the configuration file manager."
        )

    async def authenticate(self, username: str, password: str) -> "PottoUser | None":
        """Verify a local username/password pair.

        Returns None on any failure (unknown user, inactive, no local password set,
        wrong password).
        """
        user = next(
            (u for u in self.user_accounts.values() if u.username == username), None
        )
        if user is None:
            return None
        if not user.is_active:
            return None
        hashed_password = self._hashed_passwords.get(user.id)
        if hashed_password is None:
            return None
        if not bcrypt.checkpw(password.encode(), hashed_password.encode()):
            return None
        return user

    async def list_resource_editors(
        self,
        resource_type: str,
        resource_identifier: str,
        requesting_user: "PottoUser | None",
    ) -> list["PottoUser"]:
        """Return the users who hold the editor role on the given resource."""
        if not await self.authorization_backend.can_view_user(requesting_user):
            raise PottoCannotViewUserException(
                "User does not have permission to view resource editors."
            )
        if resource_type != "collection":
            raise NotImplementedError(
                f"Resource type {resource_type!r} is not supported yet."
            )
        scope = PottoScope.collection_editor(resource_identifier)
        return [u for u in self.user_accounts.values() if scope in u.scopes]

    async def list_resource_viewers(
        self,
        resource_type: str,
        resource_identifier: str,
        requesting_user: "PottoUser | None",
    ) -> list["PottoUser"]:
        """Return the users who hold the viewer role on the given resource."""
        if not await self.authorization_backend.can_view_user(requesting_user):
            raise PottoCannotViewUserException(
                "User does not have permission to view resource viewers."
            )
        if resource_type != "collection":
            raise NotImplementedError(
                f"Resource type {resource_type!r} is not supported yet."
            )
        scope = PottoScope.collection_viewer(resource_identifier)
        return [u for u in self.user_accounts.values() if scope in u.scopes]


_manager_cache: dict[str, ConfigurationFileManager] = {}


def get_configuration_file_manager(
    raw_config: dict[str, Any],
    settings: "PottoSettings",
) -> ConfigurationFileManager:
    config = ConfigurationFileManagerConfiguration.model_validate(raw_config)
    key = str(config.config_file)
    if key not in _manager_cache:
        _manager_cache[key] = ConfigurationFileManager(
            config, settings.get_authorization_backend()
        )
    return _manager_cache[key]
