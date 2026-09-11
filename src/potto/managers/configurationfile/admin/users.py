from typing import (
    Any,
    cast,
    TYPE_CHECKING,
)

from starlette.requests import Request
from starlette_admin.fields import (
    BooleanField,
    JSONField,
    StringField,
)

from ....schemas.auth import PottoUser, UserFilter
from ....webapp.admin.views import _PottoAdminModelView

if TYPE_CHECKING:
    from ....config import PottoSettings


class UserView(_PottoAdminModelView):
    """Read-only starlette-admin view for local user accounts.

    The configuration-file manager never supports user mutations, so this view only
    ever offers list/search/view - create, edit and delete are all disabled.
    """

    pk_attr = "id"
    identity = "user"
    icon = "fa fa-users"
    label = "Users"
    name = "User"

    fields = (
        StringField("id"),
        StringField("username"),
        StringField("email"),
        BooleanField("is_active"),
        JSONField("scopes"),
    )

    def can_create(self, request: Request) -> bool:
        return False

    def can_edit(self, request: Request) -> bool:
        return False

    def can_delete(self, request: Request) -> bool:
        return False

    async def create(self, request: Request, data: dict[str, Any]) -> Any:
        raise NotImplementedError(
            "Creating users is not supported by the configuration file manager."
        )

    async def edit(self, request: Request, pk: Any, data: dict[str, Any]) -> Any:
        raise NotImplementedError(
            "Editing users is not supported by the configuration file manager."
        )

    async def delete(self, request: Request, pks: list[Any]) -> int | None:
        raise NotImplementedError(
            "Deleting users is not supported by the configuration file manager."
        )

    async def find_by_pk(self, request: Request, pk: Any) -> Any:
        user = cast(PottoUser, request.user)
        settings = cast("PottoSettings", request.app.state.SETTINGS)
        return await settings.get_user_account_manager().get_user(pk, user)

    async def find_by_pks(self, request: Request, pks: list[Any]) -> list[Any]:
        users = [await self.find_by_pk(request, pk) for pk in pks]
        return [u for u in users if u is not None]

    async def find_all(
        self,
        request: Request,
        skip: int = 0,
        limit: int = 100,
        where: Any = None,
        order_by: list[str] | None = None,
    ) -> list[Any]:
        user = cast(PottoUser, request.user)
        settings = cast("PottoSettings", request.app.state.SETTINGS)
        page = (skip // limit) + 1
        users, _ = await settings.get_user_account_manager().paginated_list_users(
            page=page,
            page_size=limit,
            filter_=UserFilter(username=where if isinstance(where, str) else None),
            requesting_user=user,
        )
        return users

    async def count(self, request: Request, where: Any = None) -> int:
        user = cast(PottoUser, request.user)
        settings = cast("PottoSettings", request.app.state.SETTINGS)
        _, total = await settings.get_user_account_manager().paginated_list_users(
            page_size=1,
            include_total=True,
            filter_=UserFilter(username=where if isinstance(where, str) else None),
            requesting_user=user,
        )
        return cast(int, total)
