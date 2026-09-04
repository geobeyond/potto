import logging
from typing import (
    Any,
    cast,
)

import pydantic
from starlette.requests import Request
from starlette_admin import (
    BaseField,
    RequestAction,
)
from starlette_admin.fields import (
    CollectionField,
    EnumField,
    HasMany,
    HasOne,
    JSONField,
    ListField,
    StringField,
    URLField,
)

from ...config import PottoSettings
from ...constants import ProvidedDataType
from ...exceptions import PottoException
from ...schemas.collections import (
    Collection,
    CollectionCreate,
    CollectionUpdate,
)
from ...schemas.auth import PottoUser
from ...webapp.admin.views import _PottoAdminModelView
from ...webapp.admin.fields import SpatialExtentField

from .db.queries import collections as collection_queries
from . import operations

logger = logging.getLogger(__name__)


class CollectionView(_PottoAdminModelView):
    """Custom starlette-admin view for managing collections

    This view overrides both the `create` and `edit` methods in order to ensure they
    use our own commands, thus ensuring a consistent schema is preserved whether modifications
    are done via the admin UI, the web API or the CLI.
    """

    fields = (
        Collection.identifier,
        Collection.type_,
        Collection.is_public,
        Collection.title,
        Collection.description,
        Collection.created_at,
        Collection.updated_at,
        HasOne("owner", identity="user"),
        HasMany("editors", identity="user"),
        HasMany("viewers", identity="user"),
        SpatialExtentField(name="spatial_extent"),
        Collection.crs,
        Collection.storage_crs,
        Collection.storage_crs_coordinate_epoch,
        Collection.temporal_extent_begin,
        Collection.temporal_extent_end,
        Collection.custom_page_size,
        Collection.custom_page_size_max,
        Collection.keywords,
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
        # elif field.name == "additional_links":
        #     logger.debug(f"{value=}")
        #     result = []
        #     for raw_db_link in value:
        #         serialized_link = {}
        #         for k, v in raw_db_link.items():
        #             if k == "type":
        #                 serialized_link["media_type"] = v
        #             else:
        #                 serialized_link[k] = v
        #         result.append(serialized_link)
        #     return result
        else:
            return await super().serialize_field_value(value, field, action, request)

    async def delete(self, request: Request, pks: list[Any]) -> int | None:
        user = cast(PottoUser, request.user)
        settings = cast(PottoSettings, request.app.state.SETTINGS)
        auth_backend = settings.get_authorization_backend()
        num_deleted = 0
        async with settings.get_db_session_maker()() as session:
            for pk in pks:
                try:
                    await operations.delete_collection(
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
                result = await operations.update_collection(
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
                        await operations.grant_collection_access(
                            session,
                            user,
                            auth_backend,
                            target_user_id,
                            db_collection,
                            "editor",
                        )
                elif target_user_id in new_viewer_ids:
                    if target_user_id not in current_viewer_ids:
                        await operations.grant_collection_access(
                            session,
                            user,
                            auth_backend,
                            target_user_id,
                            db_collection,
                            "viewer",
                        )
                else:
                    await operations.revoke_collection_access(
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
                return await operations.create_collection(
                    session,
                    user,
                    auth_backend,
                    to_create=CollectionCreate.model_validate(
                        {
                            **data,
                            "owner_id": user.id,
                        }
                    ),
                    potto_settings=settings,
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
