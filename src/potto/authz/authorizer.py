from typing import TYPE_CHECKING

from .protocols import AuthorizationBackendProtocol
from ..schemas.auth import (
    Principal,
    SystemPrincipal,
)

if TYPE_CHECKING:
    from ..schemas.collections import Collection
    from ..schemas.processes import Process


class PottoAuthorizer:
    _authorization_backend: AuthorizationBackendProtocol

    def __init__(self, authorization_backend: AuthorizationBackendProtocol):
        self._authorization_backend = authorization_backend

    async def can_view_collection(
        self, principal: Principal | None, collection: "Collection"
    ) -> bool:
        """Return True if the user is allowed to view the collection.

        A None user represents an unauthenticated (anonymous) visitor.
        """
        match principal:
            case SystemPrincipal():
                return True
            case _:
                return await self._authorization_backend.can_view_collection(
                    principal, collection
                )

    async def can_edit_collection(
        self, principal: Principal | None, collection: "Collection"
    ) -> bool:
        """Return True if the user is allowed to edit the collection.

        A None user represents an unauthenticated (anonymous) visitor.
        """
        match principal:
            case SystemPrincipal():
                return True
            case _:
                return await self._authorization_backend.can_edit_collection(
                    principal, collection
                )

    async def get_accessible_collection_identifiers(
        self, principal: Principal | None
    ) -> list[str] | None:
        """Return identifiers of collections accessible to the user.

        A None user represents an unauthenticated (anonymous) visitor.
        Returns None if the user has unrestricted access (e.g. admin), or a list of
        collection resource identifiers the user can explicitly access.
        """
        match principal:
            case SystemPrincipal():
                return None
            case _:
                return await self._authorization_backend.get_accessible_collection_identifiers(
                    principal
                )

    async def can_set_user_scopes(
        self,
        principal: Principal | None,
        new_scopes: list[str],
        editable_collection_identifiers: list[str],
    ) -> bool:
        """Return True if requesting_user is allowed to assign new_scopes to a target user.

        editable_collection_identifiers: identifiers of collections the requesting user
        can edit (owner or editor role), pre-fetched by the caller.
        """
        match principal:
            case SystemPrincipal():
                return True
            case _:
                return await self._authorization_backend.can_set_user_scopes(
                    principal, new_scopes, editable_collection_identifiers
                )

    async def can_assign_admin_scope(self, principal: Principal | None) -> bool:
        """Return True if requesting_user is allowed to grant the admin scope to another user."""
        match principal:
            case SystemPrincipal():
                return True
            case _:
                return await self._authorization_backend.can_assign_admin_scope(
                    principal
                )

    async def can_change_collection_owner(
        self, principal: Principal | None, collection: "Collection"
    ) -> bool:
        """Return True if user is allowed to change the owner of the collection."""
        match principal:
            case SystemPrincipal():
                return True
            case _:
                return await self._authorization_backend.can_change_collection_owner(
                    principal, collection
                )

    async def can_create_collection(self, principal: Principal | None) -> bool:
        """Return True if user is allowed to create a new collection."""
        match principal:
            case SystemPrincipal():
                return True
            case _:
                return await self._authorization_backend.can_create_collection(
                    principal
                )

    async def can_edit_server_metadata(self, principal: Principal | None) -> bool:
        """Return True if user is allowed to edit the server metadata."""
        match principal:
            case SystemPrincipal():
                return True
            case _:
                return await self._authorization_backend.can_edit_server_metadata(
                    principal
                )

    async def can_create_user(self, principal: Principal | None) -> bool:
        """Return True if user is allowed to create new local users."""
        match principal:
            case SystemPrincipal():
                return True
            case _:
                return await self._authorization_backend.can_create_user(principal)

    async def can_view_user(self, principal: Principal | None) -> bool:
        """Return True if requesting_user is allowed to view another user's account."""
        match principal:
            case SystemPrincipal():
                return True
            case _:
                return await self._authorization_backend.can_view_user(principal)

    async def can_edit_user(self, principal: Principal | None) -> bool:
        """Return True if requesting_user is allowed to modify another user's account."""
        match principal:
            case SystemPrincipal():
                return True
            case _:
                return await self._authorization_backend.can_edit_user(principal)

    async def can_delete_user(self, principal: Principal | None) -> bool:
        """Return True if requesting_user is allowed to delete another user's account."""
        match principal:
            case SystemPrincipal():
                return True
            case _:
                return await self._authorization_backend.can_delete_user(principal)

    async def can_view_process(
        self, principal: Principal | None, process: "Process"
    ) -> bool:
        """Return True if the user is allowed to view the process.

        A None user represents an unauthenticated (anonymous) visitor.
        """
        match principal:
            case SystemPrincipal():
                return True
            case _:
                return await self._authorization_backend.can_view_process(
                    principal, process
                )

    async def can_edit_process(
        self, principal: Principal | None, process: "Process"
    ) -> bool:
        """Return True if the user is allowed to edit the process.

        A None user represents an unauthenticated (anonymous) visitor.
        """
        match principal:
            case SystemPrincipal():
                return True
            case _:
                return await self._authorization_backend.can_edit_process(
                    principal, process
                )

    async def get_accessible_process_identifiers(
        self, principal: Principal | None
    ) -> list[str] | None:
        """Return identifiers of processes accessible to the user.

        A None user represents an unauthenticated (anonymous) visitor.
        Returns None if the user has unrestricted access (e.g. admin), or a list of
        process resource identifiers the user can explicitly access.
        """
        match principal:
            case SystemPrincipal():
                return None
            case _:
                return await self._authorization_backend.get_accessible_process_identifiers(
                    principal
                )

    async def can_change_process_owner(
        self, principal: Principal | None, process: "Process"
    ) -> bool:
        """Return True if user is allowed to change the owner of the process."""
        match principal:
            case SystemPrincipal():
                return True
            case _:
                return await self._authorization_backend.can_change_process_owner(
                    principal, process
                )

    async def can_create_process(self, principal: Principal | None) -> bool:
        """Return True if user is allowed to create a new process."""
        match principal:
            case SystemPrincipal():
                return True
            case _:
                return await self._authorization_backend.can_create_process(principal)
