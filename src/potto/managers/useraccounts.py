from typing import (
    Any,
    Callable,
    Literal,
    Protocol,
    TypeAlias,
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    import cyclopts
    from starlette_admin.views import BaseModelView

    from ..config import PottoSettings
    from ..schemas.auth import (
        PottoUser,
        UserAccountManagerCapabilities,
        UserCreate,
        UserCreateFromOidc,
        UserFilter,
        UserUpdate,
    )


class UserAccountProtocol(Protocol):
    """A protocol for potto user account managers."""

    async def check_health(self) -> Literal["ok", "not-ready", "error"]:
        """Check whether the manager is healthy."""

    @property
    def potto_cli_group(self) -> str:
        """The name this manager's CLI commands are grouped under (``potto <name> ...``)."""

    async def get_cli_group(self) -> "cyclopts.App | None":
        """Return a cyclopts app of this manager's own CLI commands, or None if it has none."""

    async def get_user_account_admin_view(self) -> "BaseModelView | None":
        """Return a starlette_admin view suitable for use in potto's admin ui."""

    async def get_user_account_capabilities(self) -> "UserAccountManagerCapabilities":
        """Return the manager's capabilities."""

    async def get_user(
        self,
        user_id: str,
        requesting_user: "PottoUser | None",
    ) -> "PottoUser | None":
        """Retrieve a user by id."""

    async def get_user_by_username(
        self,
        username: str,
        requesting_user: "PottoUser | None",
    ) -> "PottoUser | None":
        """Retrieve a user by username."""

    async def paginated_list_users(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        include_total: bool = False,
        filter_: "UserFilter | None" = None,
        requesting_user: "PottoUser | None",
    ) -> tuple[list["PottoUser"], int | None]:
        """Retrieve a list of users."""

    async def create_user(
        self,
        to_create: "UserCreate",
        requesting_user: "PottoUser | None",
    ) -> "PottoUser":
        """Create a new local user.

        When the manager does not support creating users this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """

    async def update_user(
        self,
        user_id: str,
        to_update: "UserUpdate",
        requesting_user: "PottoUser | None",
    ) -> "PottoUser":
        """Update an existing user.

        When the manager does not support updating users this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """

    async def delete_user(
        self,
        user_id: str,
        requesting_user: "PottoUser | None",
    ) -> None:
        """Delete a user.

        When the manager does not support deleting users this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """

    async def provision_oidc_user(self, to_create: "UserCreateFromOidc") -> "PottoUser":
        """Just-in-time provision a user from an OIDC identity provider."""

    async def authenticate(self, username: str, password: str) -> "PottoUser | None":
        """Verify a local username/password pair.

        Returns None on any failure (unknown user, inactive, no local password set,
        wrong password). Managers with no concept of local passwords (e.g. pure-OIDC
        setups) may always return None.
        """

    async def list_resource_editors(
        self,
        resource_type: str,
        resource_identifier: str,
        requesting_user: "PottoUser | None",
    ) -> list["PottoUser"]:
        """Return the users who hold the editor role on the given resource.

        ``resource_type`` allows this to eventually cover resource kinds other than
        collections (e.g. OGC API Processes).
        """

    async def list_resource_viewers(
        self,
        resource_type: str,
        resource_identifier: str,
        requesting_user: "PottoUser | None",
    ) -> list["PottoUser"]:
        """Return the users who hold the viewer role on the given resource."""


UserAccountManagerFactoryProtocol: TypeAlias = Callable[
    [dict[str, Any], "PottoSettings"],
    UserAccountProtocol,
]
