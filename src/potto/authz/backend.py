import re

from ..schemas.auth import (
    PottoScope,
    PottoUser,
)
from ..schemas.collections import Collection

_COLLECTION_SCOPE_RE = re.compile(r"^collection-(.+):(editor|viewer)$")


class LocalAuthorizationBackend:
    """Authorization backend that evaluates permissions from locally-stored user scopes."""

    async def can_view_collection(
        self, user: PottoUser | None, collection: Collection
    ) -> bool:
        if collection.is_public:
            return True
        if user is None:
            return False
        if PottoScope.ADMIN.value in user.scopes:
            return True
        if user.id == collection.owner.id:
            return True
        if PottoScope.collection_editor(collection.identifier) in user.scopes:
            return True
        if PottoScope.collection_viewer(collection.identifier) in user.scopes:
            return True
        return False

    async def can_edit_collection(
        self, user: PottoUser | None, collection: Collection
    ) -> bool:
        if user is None:
            return False
        if PottoScope.ADMIN.value in user.scopes:
            return True
        if user.id == collection.owner.id:
            return True
        if PottoScope.collection_editor(collection.identifier) in user.scopes:
            return True
        return False

    async def get_accessible_collection_identifiers(
        self, user: PottoUser | None
    ) -> list[str] | None:
        if user is None:
            return []
        if PottoScope.ADMIN.value in user.scopes:
            return None
        return [
            m.group(1)
            for scope in user.scopes
            if (m := _COLLECTION_SCOPE_RE.match(scope))
        ]

    async def can_set_user_scopes(
        self,
        requesting_user: PottoUser | None,
        new_scopes: list[str],
        editable_collection_identifiers: list[str],
    ) -> bool:
        if requesting_user is None:
            return False
        if PottoScope.ADMIN.value in requesting_user.scopes:
            return True
        editable = set(editable_collection_identifiers)
        for scope in new_scopes:
            m = _COLLECTION_SCOPE_RE.match(scope)
            if m:
                if m.group(1) not in editable:
                    return False
            else:
                return False  # non-collection scopes require admin
        return True

    async def can_assign_admin_scope(self, requesting_user: PottoUser | None) -> bool:
        if requesting_user is None:
            return False
        return PottoScope.ADMIN.value in requesting_user.scopes

    async def can_change_collection_owner(
        self, user: PottoUser | None, collection: Collection
    ) -> bool:
        if user is None:
            return False
        if PottoScope.ADMIN.value in user.scopes:
            return True
        return user.id == collection.owner.id

    async def can_create_collection(self, user: PottoUser | None) -> bool:
        return user is not None

    async def can_edit_server_metadata(self, user: PottoUser | None) -> bool:
        if user is None:
            return False
        return PottoScope.ADMIN.value in user.scopes

    async def can_create_user(self, user: PottoUser | None) -> bool:
        if user is None:
            return False
        return PottoScope.ADMIN.value in user.scopes
