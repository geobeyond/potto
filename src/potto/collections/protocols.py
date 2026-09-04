import dataclasses
from typing import (
    Any,
    Awaitable,
    Callable,
    Literal,
    Protocol,
    Sequence,
    TypeAlias,
    TYPE_CHECKING
)

if TYPE_CHECKING:
    import shapely
    from starlette_admin.contrib.sqlmodel import ModelView

    from ..config import PottoSettings
    from ..schemas.auth import PottoUser
    from ..schemas.collections import (
        Collection,
        CollectionCreate,
        CollectionUpdate,
    )
    from ..constants import CollectionType


@dataclasses.dataclass(frozen=True)
class CollectionFilter:
    identifiers: Sequence[str] | None = None
    type_: "CollectionType | None" = None
    spatial_intersect: "shapely.Geometry | None" = None


@dataclasses.dataclass(frozen=True)
class CollectionManagerCapabilities:
    supports_creation: bool = False
    supports_modification: bool = False
    supports_deletion: bool = False
    supports_granting_access: bool = False
    supports_revoking_access: bool = False


class CollectionManagerProtocol(Protocol):
    """A protocol for potto collection managers."""

    async def check_health(self) -> Literal["ok", "not-ready", "error"]:
        """Check whether the manager is healthy."""

    async def set_up(self) -> bool:
        """Ensure the manager is ready to be used by potto."""
        
    async def get_starlette_admin_view(self) -> "type[ModelView] | None":
        """Return a starlette_admin view suitable for using the in potto admin ui."""
        
    async def get_capabilities(self) -> CollectionManagerCapabilities:
        """Return the manager's capabilities."""
        
    async def get_collection(
            self,
            identifier: str,
            user: "PottoUser | None",
    ) -> "Collection | None":
        """Retrieve a collection."""

    async def paginated_list_collections(
            self,
            user: "PottoUser | None",
            *,
            page: int = 1,
            page_size: int = 20,
            include_total: bool = False,
            filter_: CollectionFilter | None = None,
    ) -> tuple[list["Collection"], int | None]:
        """Retrieve a list of collections"""

    async def create_collection(
            self,
            to_create: "CollectionCreate",
            user: "PottoUser",
    ) -> "Collection":
        """Create a new collection.

        When the manager does not support creating collections this should raise
        ``potto.collections.exceptions.CollectionManagerCapabilityNotSupported``.
        """

    async def update_collection(
            self,
            collection: "Collection",
            to_update: "CollectionUpdate",
            user: "PottoUser",
    ) -> "Collection":
        """Update an existing collection.

        When the manager does not support updating collections this should raise
        ``potto.collections.exceptions.CollectionManagerCapabilityNotSupported``.
        """

    async def delete_collection(
            self,
            identifier: str,
            user: "PottoUser",
    ) -> None:
        """Delete a collection.

        When the manager does not support deleting collections this should raise
        ``potto.collections.exceptions.CollectionManagerCapabilityNotSupported``.
        """

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
        ``potto.collections.exceptions.CollectionManagerCapabilityNotSupported``.
        """

    async def revoke_collection_access(
            self,
            *,
            revoking_user: "PottoUser",
            target_user_id: str,
            collection: "Collection",
    ) -> None:
        """Revoke a user's access to a collection.

        When the manager does not support revoking collection access this should raise
        ``potto.collections.exceptions.CollectionManagerCapabilityNotSupported``.
        """


CollectionManagerFactory: TypeAlias = Callable[
    [dict[str, Any], "PottoSettings"],
    CollectionManagerProtocol,
]
