import logging
from typing import (
    Any,
    cast,
    TYPE_CHECKING,
)

import pydantic
from starlette.requests import Request
from starlette_admin import (
    BaseField,
    RequestAction,
)
from starlette_admin.fields import (
    BooleanField,
    CollectionField,
    DateTimeField,
    EnumField,
    FloatField,
    HasMany,
    HasOne,
    IntegerField,
    JSONField,
    ListField,
    StringField,
    URLField,
)

from ....constants import CollectionType, ProvidedDataType
from ....exceptions import PottoException
from ....schemas.collections import (
    CollectionCreate,
    CollectionUpdate,
)
from ....schemas.auth import PottoUser
from ....webapp.admin.views import _PottoAdminModelView
from ....webapp.admin.fields import SpatialExtentField

if TYPE_CHECKING:
    from ....config import PottoSettings

logger = logging.getLogger(__name__)


class CollectionView(_PottoAdminModelView):
    """Custom starlette-admin view for managing collections.

    This view overrides both the `create` and `edit` methods in order to ensure they
    use our own manager, thus ensuring a consistent schema is preserved whether
    modifications are done via the admin UI, the web API or the CLI.

    Field names below match ``potto.schemas.collections.Collection`` (the schema
    returned by ``CollectionManagerProtocol``), not the private ORM model's column
    names, since this view only ever works with schema instances.
    """

    # The schema's natural key is the resource identifier, not an ORM row id.
    pk_attr = "identifier"
    # identifier is a user-supplied natural key, not an auto-generated surrogate id, so it must
    # remain editable on the create form (starlette-admin otherwise force-hides any field whose
    # name matches pk_attr from create/edit).
    form_include_pk = True
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
        DateTimeField("created_at"),
        DateTimeField("updated_at"),
        HasOne("owner", identity="user"),
        HasMany("editors", identity="user"),
        HasMany("viewers", identity="user"),
        SpatialExtentField(name="spatial_extent"),
        JSONField("crs"),
        StringField("storage_crs"),
        FloatField("storage_crs_coordinate_epoch"),
        DateTimeField("temporal_extent_begin"),
        DateTimeField("temporal_extent_end"),
        IntegerField("custom_page_size"),
        IntegerField("custom_page_size_max"),
        JSONField("keywords"),
        ListField(
            CollectionField(
                name="additional_links",
                fields=(
                    StringField(name="type", label="media type".capitalize()),
                    StringField(name="rel"),
                    URLField(name="href"),
                    JSONField(name="title"),
                    StringField(name="href_lang"),
                ),
            )
        ),
        ListField(
            CollectionField(
                name="providers",
                fields=(
                    EnumField(
                        name="data_type",
                        enum=ProvidedDataType,
                    ),
                    StringField(name="provider_name"),
                    JSONField(name="config"),
                ),
            )
        ),
    )

    exclude_fields_from_list = (
        "crs",
        "storage_crs",
        "storage_crs_coordinate_epoch",
        "description",
        "additional_links",
        "keywords",
        "spatial_extent",
        "temporal_extent_begin",
        "temporal_extent_end",
        "providers",
        "editors",
        "viewers",
        "custom_page_size",
        "custom_page_size_max",
    )
    exclude_fields_from_create = (
        "created_at",
        "updated_at",
        "editors",
        "owner",
        "viewers",
    )
    exclude_fields_from_edit = (
        "identifier",
        "created_at",
        "updated_at",
    )

    async def is_row_action_allowed(self, request: Request, name: str) -> bool:
        if name in ("edit", "delete"):
            settings = cast("PottoSettings", request.app.state.SETTINGS)
            collection_manager = settings.get_collection_manager()
            capabilities = await collection_manager.get_collection_capabilities()

            if name == "edit" and not capabilities.supports_modification:
                return False
            if name == "delete" and not capabilities.supports_deletion:
                return False

            pk = request.path_params.get("pk")
            if pk is not None:
                user = cast(PottoUser, request.user)
                authorizer = settings.get_authorizer()
                if (
                    collection := await collection_manager.get_collection(
                        identifier=pk, user=user
                    )
                ) is not None:
                    return await authorizer.can_edit_collection(user, collection)
        return await super().is_row_action_allowed(request, name)

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

    async def serialize(
        self,
        obj: Any,
        request: Request,
        action: RequestAction,
        include_relationships: bool = True,
        include_select2: bool = False,
    ) -> dict[str, Any]:
        result = await super().serialize(
            obj, request, action, include_relationships, include_select2
        )
        if action == RequestAction.LIST:
            user = cast(PottoUser, request.user)
            settings = cast("PottoSettings", request.app.state.SETTINGS)
            collection_manager = settings.get_collection_manager()
            capabilities = await collection_manager.get_collection_capabilities()
            can_edit = capabilities.supports_modification

            authorizer = settings.get_authorizer()
            result["_meta"]["can_edit"] = can_edit and (
                await authorizer.can_edit_collection(user, obj)
            )
        return result

    async def serialize_field_value(
        self,
        value: Any,
        field: BaseField,
        action: RequestAction,
        request: Request,
    ) -> Any:
        if field.name == "providers":
            value: dict[ProvidedDataType, Any]
            result = []
            for type_, prov in value.items():
                result.append(
                    {
                        "data_type": ProvidedDataType(type_),
                        "provider_name": prov.provider_name,
                        "config": prov.config,
                    }
                )
            return result
        else:
            return await super().serialize_field_value(value, field, action, request)

    async def delete(self, request: Request, pks: list[Any]) -> int | None:
        user = cast(PottoUser, request.user)
        settings = cast("PottoSettings", request.app.state.SETTINGS)
        collection_manager = settings.get_collection_manager()
        capabilities = await collection_manager.get_collection_capabilities()

        if not capabilities.supports_deletion:
            return self.handle_exception(PottoException("Cannot delete collection"))

        num_deleted = 0
        for pk in pks:
            try:
                await collection_manager.delete_collection(pk, user)
            except PottoException as err:
                return self.handle_exception(err)
            num_deleted += 1

        return num_deleted

    async def edit(self, request: Request, pk: Any, data: dict[str, Any]) -> Any:
        user = cast(PottoUser, request.user)
        data["providers"] = self._adapt_request_providers_to_internal_model(
            data["providers"]
        )
        new_editor_ids = set(data.pop("editors", None) or [])
        new_viewer_ids = set(data.pop("viewers", None) or [])
        # The form field is named after schemas.collections.Collection's "type_"
        # (the read shape), but CollectionUpdate (the write shape) calls it
        # "collection_type" - resource identifiers aren't editable at all, so no
        # equivalent rename is needed for "identifier".
        if "type_" in data:
            data["collection_type"] = data.pop("type_")
        data.pop("identifier", None)
        to_set = {
            **{k: v for k, v in data.items() if k != "owner"},
            "owner_id": data.get("owner"),
        }
        settings = cast("PottoSettings", request.app.state.SETTINGS)
        collection_manager = settings.get_collection_manager()
        user_account_manager = settings.get_user_account_manager()

        collection = await collection_manager.get_collection(pk, user)
        if collection is None:
            raise PottoException(f"Collection {pk} not found")
        try:
            updated = await collection_manager.update_collection(
                collection,
                CollectionUpdate(**{k: v for k, v in to_set.items() if v is not None}),
                user,
            )
        except (pydantic.ValidationError, PottoException) as err:
            return self.handle_exception(err)

        current_editors = await user_account_manager.list_resource_editors(
            "collection", updated.identifier, user
        )
        current_viewers = await user_account_manager.list_resource_viewers(
            "collection", updated.identifier, user
        )
        current_editor_ids = {e.id for e in current_editors}
        current_viewer_ids = {v.id for v in current_viewers}
        for target_user_id in (
            current_editor_ids | current_viewer_ids | new_editor_ids | new_viewer_ids
        ):
            if target_user_id in new_editor_ids:
                if target_user_id not in current_editor_ids:
                    await collection_manager.grant_collection_access(
                        granting_user=user,
                        target_user_id=target_user_id,
                        collection=updated,
                        role="editor",
                    )
            elif target_user_id in new_viewer_ids:
                if target_user_id not in current_viewer_ids:
                    await collection_manager.grant_collection_access(
                        granting_user=user,
                        target_user_id=target_user_id,
                        collection=updated,
                        role="viewer",
                    )
            else:
                await collection_manager.revoke_collection_access(
                    revoking_user=user,
                    target_user_id=target_user_id,
                    collection=updated,
                )
        return updated

    async def create(self, request: Request, data: dict[str, Any]) -> Any:
        user = cast(PottoUser, request.user)
        data["providers"] = self._adapt_request_providers_to_internal_model(
            data["providers"]
        )
        # See the equivalent rename note in edit() - CollectionCreate uses the
        # write-side field names, not the read-side ones the form is built from.
        data["resource_identifier"] = data.pop("identifier")
        data["collection_type"] = data.pop("type_")
        settings = cast("PottoSettings", request.app.state.SETTINGS)
        collection_manager = settings.get_collection_manager()
        try:
            return await collection_manager.create_collection(
                CollectionCreate.model_validate({**data, "owner_id": user.id}), user
            )
        except (pydantic.ValidationError, PottoException) as err:
            return self.handle_exception(err)

    def _adapt_request_providers_to_internal_model(
        self, request_providers: list[dict]
    ) -> dict[str, dict]:
        """Admin form gets providers as a list but we then store as a dict.

        This also means that it is not possible to store more than one
        provider of each data type.
        """
        new_providers = {}
        for sent_provider in request_providers:
            new_providers[sent_provider.pop("data_type")] = sent_provider
        return new_providers
