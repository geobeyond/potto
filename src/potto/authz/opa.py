import logging
from typing import cast

import httpx

from ..db.models import Collection
from ..schemas.auth import PottoUser

logger = logging.getLogger(__name__)


class OPAAuthorizationBackend:
    """Authorization backend that delegates policy decisions to Open Policy Agent."""

    def __init__(self, opa_url: str, policy_path: str = "potto/authz") -> None:
        self._base_url = opa_url.rstrip("/")
        self._policy_path = policy_path.strip("/")

    async def _query(self, rule: str, input_data: dict) -> object | list | bool | None:
        url = f"{self._base_url}/v1/data/{self._policy_path}/{rule}"
        logger.debug(f"{url=}")
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={"input": input_data})
            response.raise_for_status()
            return response.json().get("result")

    def _user_input(self, user: PottoUser | None) -> dict | None:
        if user is None:
            return None
        return {
            "id": user.id,
            "username": user.username,
            "scopes": user.scopes,
        }

    def _collection_input(self, collection: Collection) -> dict:
        return {
            "id": collection.id,
            "resource_identifier": collection.resource_identifier,
            "is_public": collection.is_public,
            "owner_id": collection.owner_id,
        }

    async def can_view_collection(
        self, user: PottoUser | None, collection: Collection
    ) -> bool:
        result = await self._query(
            "can_view_collection",
            {
                "user": self._user_input(user),
                "collection": self._collection_input(collection),
            },
        )
        return bool(result)

    async def can_edit_collection(
        self, user: PottoUser | None, collection: Collection
    ) -> bool:
        result = await self._query(
            "can_edit_collection",
            {
                "user": self._user_input(user),
                "collection": self._collection_input(collection),
            },
        )
        return bool(result)

    async def get_accessible_collection_identifiers(
        self, user: PottoUser | None
    ) -> list[str] | None:
        result = await self._query(
            "accessible_collection_identifiers",
            {"user": self._user_input(user)},
        )
        if result is None:
            return None
        result = cast(list[str], result)
        return result

    async def can_set_user_scopes(
        self,
        requesting_user: PottoUser | None,
        new_scopes: list[str],
        editable_collection_identifiers: list[str],
    ) -> bool:
        result = await self._query(
            "can_set_user_scopes",
            {
                "user": self._user_input(requesting_user),
                "new_scopes": new_scopes,
                "editable_collection_identifiers": editable_collection_identifiers,
            },
        )
        return bool(result)

    async def can_assign_admin_scope(self, requesting_user: PottoUser | None) -> bool:
        result = await self._query(
            "can_assign_admin_scope",
            {"user": self._user_input(requesting_user)},
        )
        return bool(result)

    async def can_change_collection_owner(
        self, user: PottoUser | None, collection: Collection
    ) -> bool:
        result = await self._query(
            "can_change_collection_owner",
            {
                "user": self._user_input(user),
                "collection": self._collection_input(collection),
            },
        )
        return bool(result)

    async def can_create_collection(self, user: PottoUser | None) -> bool:
        result = await self._query(
            "can_create_collection",
            {"user": self._user_input(user)},
        )
        return bool(result)

    async def can_edit_server_metadata(self, user: PottoUser | None) -> bool:
        result = await self._query(
            "can_edit_server_metadata",
            {"user": self._user_input(user)},
        )
        return bool(result)

    async def can_create_user(self, user: PottoUser | None) -> bool:
        return False
