from typing import (
    Any,
    cast,
    TYPE_CHECKING,
)

from starlette.requests import Request
from starlette_admin import (
    BaseField,
    RequestAction,
)
from starlette_admin.fields import (
    BooleanField,
    DateTimeField,
    EnumField,
    ListField,
    StringField,
)

from ....constants import CollectionType
from ....schemas.auth import PottoUser
from ....webapp.admin.views import _PottoAdminModelView

if TYPE_CHECKING:
    from ....config import PottoSettings


class CollectionView(_PottoAdminModelView):
    """Read-only starlette-admin view for collections.

    The configuration-file manager never supports collection mutations, so this view
    only ever offers list/search/view - create, edit and delete are all disabled.
    Field names below match ``potto.schemas.collections.Collection`` (the schema
    returned by ``CollectionManagerProtocol``), since this view only ever works with
    schema instances.
    """

    pk_attr = "identifier"
    identity = "collection_item"
    icon = "fa fa-database"
    label = "Collections"
    name = "Collection"

    fields = (
        StringField("identifier", label="Resource identifier"),
        EnumField("type_", label="Collection type", enum=CollectionType),
        BooleanField("is_public"),
        StringField("title"),
        StringField("description"),
        StringField("owner"),
        ListField(StringField("editors")),
        ListField(StringField("viewers")),
        DateTimeField("created_at"),
        DateTimeField("updated_at"),
        StringField("spatial_extent"),
    )

    exclude_fields_from_list = (
        "description",
        "spatial_extent",
        "editors",
        "viewers",
        "updated_at",
    )

    def can_create(self, request: Request) -> bool:
        return False

    def can_edit(self, request: Request) -> bool:
        return False

    def can_delete(self, request: Request) -> bool:
        return False

    async def create(self, request: Request, data: dict[str, Any]) -> Any:
        raise NotImplementedError(
            "Creating collections is not supported by the configuration file manager."
        )

    async def edit(self, request: Request, pk: Any, data: dict[str, Any]) -> Any:
        raise NotImplementedError(
            "Editing collections is not supported by the configuration file manager."
        )

    async def delete(self, request: Request, pks: list[Any]) -> int | None:
        raise NotImplementedError(
            "Deleting collections is not supported by the configuration file manager."
        )

    async def find_by_pk(self, request: Request, pk: Any) -> Any:
        user = cast(PottoUser, request.user)
        settings = cast("PottoSettings", request.app.state.SETTINGS)
        collection_manager = settings.get_collection_manager()
        authorizer = settings.get_authorizer()
        collection = await collection_manager.get_collection(pk, user)
        if collection is None:
            return None
        if not await authorizer.can_view_collection(user, collection):
            return None
        user_account_manager = settings.get_user_account_manager()
        editors = await user_account_manager.list_resource_editors(
            "collection", collection.identifier, user
        )
        viewers = await user_account_manager.list_resource_viewers(
            "collection", collection.identifier, user
        )
        object.__setattr__(collection, "editors", editors)
        object.__setattr__(collection, "viewers", viewers)
        return collection

    async def find_by_pks(self, request: Request, pks: list[Any]) -> list[Any]:
        collections = [await self.find_by_pk(request, pk) for pk in pks]
        return [c for c in collections if c is not None]

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
        collection_manager = settings.get_collection_manager()
        page = (skip // limit) + 1
        collections, _ = await collection_manager.paginated_list_collections(
            user,
            page=page,
            page_size=limit,
        )
        return collections

    async def count(self, request: Request, where: Any = None) -> int:
        user = cast(PottoUser, request.user)
        settings = cast("PottoSettings", request.app.state.SETTINGS)
        collection_manager = settings.get_collection_manager()
        _, total = await collection_manager.paginated_list_collections(
            user, page_size=1, include_total=True
        )
        return cast(int, total)

    async def serialize_field_value(
        self,
        value: Any,
        field: BaseField,
        action: RequestAction,
        request: Request,
    ) -> Any:
        if field.name == "owner":
            return value.username
        if field.name in ("editors", "viewers"):
            return [u.username for u in value]
        if field.name == "spatial_extent":
            return str(value) if value is not None else None
        return await super().serialize_field_value(value, field, action, request)
