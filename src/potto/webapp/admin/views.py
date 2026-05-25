import json
import logging
from typing import (
    Any,
    cast,
    List,
    Optional,
)

import pydantic
from starlette.requests import Request
from starlette_admin import (
    BaseField,
    RequestAction,
)
from starlette_admin.contrib.sqlmodel import ModelView
from starlette_admin.exceptions import FormValidationError
from starlette_admin.fields import (
    CollectionField,
    EnumField,
    HasMany,
    HasOne,
    JSONField,
    ListField,
    PasswordField,
    StringField,
    URLField,
)

from ...config import PottoSettings
from ...exceptions import (
    PottoCannotChangeCollectionOwnerException,
    PottoCannotCreateCollectionException,
    PottoCannotCreateUserException,
    PottoCannotEditCollectionException,
    PottoCannotEditServerMetadataException,
    PottoCannotSetAdminScopeException,
    PottoCannotSetScopesException,
    PottoException,
)
from ...operations import collections as collection_operations
from ...operations import auth as auth_operations
from ...operations import metadata as metadata_operations
from ...db.models import (
    Collection,
    User,
)
from ...db.queries import (
    auth as auth_queries,
    collections as collection_queries,
)
from ...schemas.base import ProvidedDataType
from ...schemas.collections import (
    CollectionCreate,
    CollectionUpdate,
)
from ...schemas.auth import (
    PottoUser,
    UserCreate,
    UserUpdate,
)
from ...schemas.metadata import (
    DataProviderInformation,
    LicenseInformation,
    PointOfContact,
    ServerMetadataUpdate,
)
from .fields import SpatialExtentField

logger = logging.getLogger(__name__)


class _PottoAdminModelView(ModelView):
    def handle_exception(self, exc: Exception) -> None:
        if isinstance(
            exc, (PottoCannotSetAdminScopeException, PottoCannotSetScopesException)
        ):
            raise FormValidationError({"scopes": str(exc)})
        if isinstance(exc, PottoCannotChangeCollectionOwnerException):
            raise FormValidationError({"owner": str(exc)})
        if isinstance(exc, PottoCannotEditCollectionException):
            raise FormValidationError({"resource_identifier": str(exc)})
        if isinstance(exc, PottoCannotCreateCollectionException):
            raise FormValidationError({"resource_identifier": str(exc)})
        if isinstance(exc, PottoCannotEditServerMetadataException):
            raise FormValidationError({"title": str(exc)})
        if isinstance(exc, PottoCannotCreateUserException):
            raise FormValidationError({"username": str(exc)})
        logger.exception("An error occurred", exc)
        return super().handle_exception(exc)


class UserView(_PottoAdminModelView):
    """Custom starlette-admin view for managing local users

    This view overrides both the `create` and `edit` methods in order to ensure they
    use our own db commands, thus ensuring a consistent schema is preserved whether modifications
    are done via the admin UI, the web API or the CLI.

    User creation is restricted to admins and only available when using the local
    authorization backend (not supported with OPA).
    """

    async def async_can_create(self, request: Request) -> bool:
        user = cast(PottoUser, request.user)
        settings = cast(PottoSettings, request.app.state.SETTINGS)
        return await settings.get_authorization_backend().can_create_user(user)

    fields = (
        User.username,
        User.email,
        PasswordField("password"),
        User.is_active,
        User.scopes,
    )
    exclude_fields_from_detail = ("password",)
    exclude_fields_from_list = ("password",)

    async def create(self, request: Request, data: dict[str, Any]) -> Any:
        user = cast(PottoUser, request.user)
        settings = cast(PottoSettings, request.app.state.SETTINGS)
        auth_backend = settings.get_authorization_backend()
        async with settings.get_db_session_maker()() as session:
            try:
                return await auth_operations.create_user(
                    session,
                    requesting_user=user,
                    authorization_backend=auth_backend,
                    to_create=UserCreate(
                        **{
                            k: v
                            for k, v in {
                                "username": data["username"],
                                "is_active": data["is_active"],
                                "email": data["email"] or None,
                                "scopes": data["scopes"] or None,
                                "password": data["password"],
                            }.items()
                            if v is not None
                        }
                    ),
                )
            except pydantic.ValidationError as err:
                self.handle_exception(err)
            except PottoException as err:
                self.handle_exception(err)

    async def edit(self, request: Request, pk: Any, data: dict[str, Any]) -> Any:
        user = cast(PottoUser, request.user)
        settings = cast(PottoSettings, request.app.state.SETTINGS)
        auth_backend = settings.get_authorization_backend()
        async with settings.get_db_session_maker()() as session:
            if (db_user := await auth_queries.get_user(session, pk)) is None:
                raise RuntimeError(f"User {pk} not found")
            try:
                return await auth_operations.update_user(
                    session,
                    requesting_user=user,
                    authorization_backend=auth_backend,
                    db_user=db_user,
                    to_update=UserUpdate(
                        **{
                            k: v
                            for k, v in {
                                "username": data["username"],
                                "is_active": data["is_active"],
                                "email": data["email"] or None,
                                "scopes": data["scopes"] or None,
                                "password": data["password"] or None,
                            }.items()
                            if v is not None
                        }
                    ),
                )
            except pydantic.ValidationError as err:
                return self.handle_exception(err)
            except PottoException as err:
                self.handle_exception(err)


class CollectionView(_PottoAdminModelView):
    """Custom starlette-admin view for managing collections

    This view overrides both the `create` and `edit` methods in order to ensure they
    use our own commands, thus ensuring a consistent schema is preserved whether modifications
    are done via the admin UI, the web API or the CLI.
    """

    fields = (
        Collection.resource_identifier,
        Collection.collection_type,
        Collection.is_public,
        Collection.title,
        Collection.description,
        Collection.created_at,
        Collection.updated_at,
        HasOne("owner", identity="user"),
        HasMany("editors", identity="user"),
        HasMany("viewers", identity="user"),
        SpatialExtentField(name="spatial_extent"),
        Collection.spatial_extent_crs,
        Collection.crs,
        Collection.storage_crs,
        Collection.storage_crs_coordinate_epoch,
        Collection.temporal_extent_begin,
        Collection.temporal_extent_end,
        Collection.custom_page_size,
        Collection.custom_page_size_max,
        Collection.keywords,
        # JSONField(name="providers"),
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
        ListField(
            CollectionField(
                name="additional_links",
                fields=(
                    StringField(name="media_type"),
                    StringField(name="rel"),
                    URLField(name="href"),
                    JSONField(name="title"),
                    StringField(name="href_lang"),
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
        "spatial_extent_crs",
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
        "created_at",
        "updated_at",
    )

    async def is_row_action_allowed(self, request: Request, name: str) -> bool:
        logger.debug(f"{name=}")
        if name in ("edit", "delete"):
            pk = request.path_params.get("pk")
            if pk is not None:
                user = cast(PottoUser, request.user)
                settings = cast(PottoSettings, request.app.state.SETTINGS)
                auth_backend = settings.get_authorization_backend()
                async with settings.get_db_session_maker()() as session:
                    collection = await collection_queries.get_collection(
                        session, int(pk)
                    )
                if collection is not None:
                    return await auth_backend.can_edit_collection(user, collection)
        return await super().is_row_action_allowed(request, name)

    async def find_by_pk(self, request: Request, pk: Any) -> Any:
        user = cast(PottoUser, request.user)
        settings = cast(PottoSettings, request.app.state.SETTINGS)
        auth_backend = settings.get_authorization_backend()
        async with settings.get_db_session_maker()() as session:
            collection = await collection_queries.get_collection(session, int(pk))
            if collection is None:
                return None
            if not await auth_backend.can_view_collection(user, collection):
                return None
            editors = await collection_queries.get_collection_editors(
                session, collection.resource_identifier
            )
            viewers = await collection_queries.get_collection_viewers(
                session, collection.resource_identifier
            )
        object.__setattr__(collection, "editors", editors)
        object.__setattr__(collection, "viewers", viewers)
        return collection

    async def find_all(
        self,
        request: Request,
        skip: int = 0,
        limit: int = 100,
        where: Any = None,
        order_by: list[str] | None = None,
    ) -> list[Any]:
        user = cast(PottoUser, request.user)
        settings = cast(PottoSettings, request.app.state.SETTINGS)
        auth_backend = settings.get_authorization_backend()
        async with settings.get_db_session_maker()() as session:
            accessible_ids = await auth_backend.get_accessible_collection_identifiers(
                user
            )
            items, _ = await collection_queries.list_user_collections(
                session,
                offset=skip,
                limit=limit,
                user_id=user.id,
                accessible_identifiers=accessible_ids,
            )
        return items

    async def count(self, request: Request, where: Any = None) -> int:
        user = cast(PottoUser, request.user)
        settings = cast(PottoSettings, request.app.state.SETTINGS)
        auth_backend = settings.get_authorization_backend()
        async with settings.get_db_session_maker()() as session:
            accessible_ids = await auth_backend.get_accessible_collection_identifiers(
                user
            )
            _, total = await collection_queries.list_user_collections(
                session,
                limit=1,
                user_id=user.id,
                accessible_identifiers=accessible_ids,
                include_total=True,
            )
        return total or 0

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
            settings = cast(PottoSettings, request.app.state.SETTINGS)
            auth_backend = settings.get_authorization_backend()
            result["_meta"]["can_edit"] = await auth_backend.can_edit_collection(
                user, obj
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
            logger.debug(f"{value=}")
            value: dict[str, dict[str, Any]]
            result = []
            for type_, prov in value.items():
                result.append(
                    {
                        "data_type": ProvidedDataType(type_),
                        "provider_name": prov["provider_name"],
                        "config": prov["config"],
                    }
                )
            return result
        else:
            return await super().serialize_field_value(value, field, action, request)

    async def delete(self, request: Request, pks: List[Any]) -> Optional[int]:
        user = cast(PottoUser, request.user)
        settings = cast(PottoSettings, request.app.state.SETTINGS)
        auth_backend = settings.get_authorization_backend()
        num_deleted = 0
        async with settings.get_db_session_maker()() as session:
            for pk in pks:
                try:
                    await collection_operations.delete_collection(
                        session, user, auth_backend, int(pk)
                    )
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
        logger.debug(f"{data=}")
        to_set = {
            **{k: v for k, v in data.items() if k != "owner"},
            "owner_id": data.get("owner"),
        }
        settings = cast(PottoSettings, request.app.state.SETTINGS)
        auth_backend = settings.get_authorization_backend()
        async with settings.get_db_session_maker()() as session:
            db_collection = await collection_queries.get_collection(session, int(pk))
            if db_collection is None:
                raise RuntimeError(f"Collection {pk} not found")
            try:
                result = await collection_operations.update_collection(
                    session,
                    user,
                    auth_backend,
                    db_collection,
                    to_update=CollectionUpdate(
                        **{k: v for k, v in to_set.items() if v is not None},
                    ),
                )
            except (pydantic.ValidationError, PottoException) as err:
                return self.handle_exception(err)
            current_editors = await collection_queries.get_collection_editors(
                session, db_collection.resource_identifier
            )
            current_viewers = await collection_queries.get_collection_viewers(
                session, db_collection.resource_identifier
            )
            current_editor_ids = {e.id for e in current_editors}
            current_viewer_ids = {v.id for v in current_viewers}
            for target_user_id in (
                current_editor_ids
                | current_viewer_ids
                | new_editor_ids
                | new_viewer_ids
            ):
                if target_user_id in new_editor_ids:
                    if target_user_id not in current_editor_ids:
                        await collection_operations.grant_collection_access(
                            session,
                            user,
                            auth_backend,
                            target_user_id,
                            db_collection,
                            "editor",
                        )
                elif target_user_id in new_viewer_ids:
                    if target_user_id not in current_viewer_ids:
                        await collection_operations.grant_collection_access(
                            session,
                            user,
                            auth_backend,
                            target_user_id,
                            db_collection,
                            "viewer",
                        )
                else:
                    await collection_operations.revoke_collection_access(
                        session, user, auth_backend, target_user_id, db_collection
                    )
            return result

    async def create(self, request: Request, data: dict[str, Any]) -> Any:
        user = cast(PottoUser, request.user)
        data["providers"] = self._adapt_request_providers_to_internal_model(
            data["providers"]
        )
        settings = cast(PottoSettings, request.app.state.SETTINGS)
        auth_backend = settings.get_authorization_backend()
        logger.debug(f"{data=}")
        async with settings.get_db_session_maker()() as session:
            try:
                return await collection_operations.create_collection(
                    session,
                    user,
                    auth_backend,
                    to_create=CollectionCreate.model_validate(
                        {
                            **data,
                            "owner_id": user.id,
                        }
                    ),
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


class ServerMetadataModelView(_PottoAdminModelView):
    """Custom starlette-admin view for managing server metadata.

    The server can only have a single ServerMetadata instance, so this view skips
    the list page entirely (redirecting straight to edit) and disables create/delete.
    Starlette-admin's field and form machinery is reused for the edit form.
    """

    skip_list = True

    def can_create(self, request: Request) -> bool:
        return False

    def can_delete(self, request: Request) -> bool:
        return False

    async def async_can_edit(self, request: Request) -> bool:
        user = cast(PottoUser, request.user)
        settings = cast(PottoSettings, request.app.state.SETTINGS)
        return await settings.get_authorization_backend().can_edit_server_metadata(user)

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
        settings = cast(PottoSettings, request.app.state.SETTINGS)
        async with settings.get_db_session_maker()() as session:
            return [await metadata_operations.get_server_metadata(session)]

    async def count(self, request: Request, where: Any = None) -> int:
        return 1

    async def find_by_pk(self, request: Request, pk: Any) -> Any:
        settings = cast(PottoSettings, request.app.state.SETTINGS)
        async with settings.get_db_session_maker()() as session:
            return await metadata_operations.get_server_metadata(session)

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
        settings = cast(PottoSettings, request.app.state.SETTINGS)
        auth_backend = settings.get_authorization_backend()
        lic_data = data.get("license") or {}
        dp_data = data.get("data_provider") or {}
        poc_data = data.get("point_of_contact") or {}
        poc_values = {k: v or None for k, v in poc_data.items()}
        try:
            async with settings.get_db_session_maker()() as session:
                return await metadata_operations.update_server_metadata(
                    session,
                    user,
                    auth_backend,
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
                )
        except PottoException as err:
            self.handle_exception(err)
