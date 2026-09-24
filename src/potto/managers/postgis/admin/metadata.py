import json
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
    CollectionField,
    JSONField,
    StringField,
    URLField,
)

from ....exceptions import PottoException
from ....schemas.auth import PottoUser
from ....schemas.metadata import (
    DataProviderInformation,
    LicenseInformation,
    PointOfContact,
    ServerMetadataUpdate,
)
from ....webapp.admin.views import _PottoAdminModelView

if TYPE_CHECKING:
    from ....config import PottoSettings


class ServerMetadataModelView(_PottoAdminModelView):
    """Custom starlette-admin view for managing server metadata.

    The server can only have a single ServerMetadata instance, so this view skips
    the list page entirely (redirecting straight to edit) and disables create/delete.
    Starlette-admin's field and form machinery is reused for the edit form.
    """

    skip_list = True
    identity = "server_metadata"
    icon = "fa fa-server"
    label = "Server Metadata"
    name = "Server Metadata"
    # Placeholder: schemas.metadata.ServerMetadata (the object every data-access method here
    # returns) has no real primary key at all - it's a singleton resource. get_pk_value/
    # get_serialized_pk_value are overridden below to return a fixed value instead of doing a
    # bare getattr(obj, pk_attr), which would otherwise raise AttributeError.
    pk_attr = "id"

    def can_create(self, request: Request) -> bool:
        return False

    def can_delete(self, request: Request) -> bool:
        return False

    async def get_pk_value(self, request: Request, obj: Any) -> Any:
        return "server-metadata"

    async def get_serialized_pk_value(self, request: Request, obj: Any) -> Any:
        return "server-metadata"

    async def async_can_edit(self, request: Request) -> bool:
        user = cast(PottoUser, request.user)
        settings = cast("PottoSettings", request.app.state.SETTINGS)
        return await settings.get_authorizer().can_edit_server_metadata(user)

    async def is_row_action_allowed(self, request: Request, name: str) -> bool:
        if name == "edit":
            return await self.async_can_edit(request)
        return await super().is_row_action_allowed(request, name)

    fields = (
        StringField("title", required=True),
        StringField("description"),
        JSONField("keywords"),
        StringField("keywords_type"),
        StringField("terms_of_service"),
        URLField("url"),
        CollectionField(
            "license",
            fields=(
                StringField("name"),
                URLField("url"),
            ),
        ),
        CollectionField(
            "data_provider",
            fields=(
                StringField("name"),
                URLField("url"),
            ),
        ),
        CollectionField(
            "point_of_contact",
            fields=(
                StringField("name"),
                StringField("position"),
                StringField("address"),
                StringField("city"),
                StringField("state_or_province"),
                StringField("postal_code"),
                StringField("country"),
                StringField("phone"),
                StringField("fax"),
                StringField("email"),
                URLField("url"),
                StringField("contact_hours"),
                StringField("contact_instructions"),
            ),
        ),
    )

    async def find_all(
        self,
        request: Request,
        skip: int = 0,
        limit: int = 100,
        where: Any = None,
        order_by: list[str] | None = None,
    ) -> list[Any]:
        settings = cast("PottoSettings", request.app.state.SETTINGS)
        return [await settings.get_server_metadata_manager().get_server_metadata()]

    async def count(self, request: Request, where: Any = None) -> int:
        return 1

    async def find_by_pk(self, request: Request, pk: Any) -> Any:
        settings = cast("PottoSettings", request.app.state.SETTINGS)
        return await settings.get_server_metadata_manager().get_server_metadata()

    async def find_by_pks(self, request: Request, pks: list[Any]) -> list[Any]:
        return [await self.find_by_pk(request, pk) for pk in pks]

    async def serialize_field_value(
        self, value: Any, field: BaseField, action: RequestAction, request: Request
    ) -> Any:
        if field.name in ("title", "description", "terms_of_service") and isinstance(
            value, dict
        ):
            return json.dumps(value)
        return await super().serialize_field_value(value, field, action, request)

    async def edit(self, request: Request, pk: Any, data: dict[str, Any]) -> Any:
        user = cast(PottoUser, request.user)
        settings = cast("PottoSettings", request.app.state.SETTINGS)
        server_metadata_manager = settings.get_server_metadata_manager()
        lic_data = data.get("license") or {}
        dp_data = data.get("data_provider") or {}
        poc_data = data.get("point_of_contact") or {}
        poc_values = {k: v or None for k, v in poc_data.items()}
        try:
            return await server_metadata_manager.update_server_metadata(
                ServerMetadataUpdate(
                    title=data.get("title") or None,
                    description=data.get("description") or None,
                    keywords=data.get("keywords"),
                    keywords_type=data.get("keywords_type") or None,
                    terms_of_service=data.get("terms_of_service") or None,
                    url=data.get("url") or None,
                    license=LicenseInformation(
                        name=lic_data["name"],
                        url=lic_data.get("url") or None,
                    )
                    if lic_data.get("name")
                    else None,
                    data_provider=DataProviderInformation(
                        name=dp_data["name"],
                        url=dp_data.get("url") or None,
                    )
                    if dp_data.get("name")
                    else None,
                    point_of_contact=PointOfContact.model_validate(poc_values)
                    if any(poc_values.values())
                    else None,
                ),
                user,
            )
        except PottoException as err:
            self.handle_exception(err)
