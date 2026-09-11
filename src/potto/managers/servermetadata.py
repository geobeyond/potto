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
    from ..schemas.auth import PottoUser
    from ..schemas.metadata import (
        ServerMetadata,
        ServerMetadataManagerCapabilities,
        ServerMetadataUpdate,
    )


class ServerMetadataProtocol(Protocol):
    """A protocol for potto server metadata managers."""

    async def check_health(self) -> Literal["ok", "not-ready", "error"]:
        """Check whether the manager is healthy."""

    @property
    def potto_cli_group(self) -> str:
        """The name this manager's CLI commands are grouped under (``potto <name> ...``)."""

    async def get_cli_group(self) -> "cyclopts.App | None":
        """Return a cyclopts app of this manager's own CLI commands, or None if it has none."""

    async def get_server_metadata_admin_view(self) -> "BaseModelView | None":
        """Return a starlette_admin view suitable for use in potto's admin ui."""

    async def get_server_metadata_capabilities(
        self,
    ) -> "ServerMetadataManagerCapabilities":
        """Return the manager's capabilities."""

    async def get_server_metadata(self) -> "ServerMetadata":
        """Return pre-existing server metadata, creating a default record if none exists."""

    async def update_server_metadata(
        self,
        to_update: "ServerMetadataUpdate",
        user: "PottoUser | None",
    ) -> "ServerMetadata":
        """Update the server's metadata.

        When the manager does not support updating metadata this should raise
        ``potto.exceptions.CapabilityNotSupported``.
        """


ServerMetadataManagerFactoryProtocol: TypeAlias = Callable[
    [dict[str, Any], "PottoSettings"],
    ServerMetadataProtocol,
]
