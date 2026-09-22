import dataclasses
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
    HasMany,
    HasOne,
    IntegerField,
    JSONField,
    ListField,
    StringField,
    URLField,
)

from ....exceptions import PottoException
from ....schemas.processes import (
    ProcessCreate,
    ProcessExecutionUnitCwl,
    ProcessExecutionUnitOci,
    ProcessExecutionUnitOther,
    ProcessUpdate,
)
from ....schemas.auth import PottoUser
from ....webapp.admin.views import _PottoAdminModelView

if TYPE_CHECKING:
    from ....config import PottoSettings

logger = logging.getLogger(__name__)

_INPUT_OUTPUT_FIELDS = (
    StringField(name="title"),
    JSONField(name="schema"),
    IntegerField(name="min_occurs"),
    StringField(name="max_occurs", help_text="An integer, or 'unbounded'"),
    StringField(name="description"),
    JSONField(name="keywords"),
)

_OCI_BINDING_RENAMES = {
    "value_from": "valueFrom",
    "item_separator": "itemSeparator",
    "shell_quote": "shellQuote",
}


def _binding_to_camel_case(binding: dict) -> dict:
    return {_OCI_BINDING_RENAMES.get(k, k): v for k, v in binding.items()}


class ProcessView(_PottoAdminModelView):
    """Custom starlette-admin view for managing processes.

    This view overrides both the `create` and `edit` methods in order to ensure they
    use our own manager, thus ensuring a consistent schema is preserved whether
    modifications are done via the admin UI, the web API or the CLI.

    Field names below match ``potto.schemas.processes.Process`` (the schema
    returned by ``ProcessManagerProtocol``), not the private ORM model's column
    names, since this view only ever works with schema instances.
    """

    # The schema's natural key is the resource identifier, not an ORM row id.
    pk_attr = "identifier"
    # identifier is a user-supplied natural key, not an auto-generated surrogate id, so it must
    # remain editable on the create form (starlette-admin otherwise force-hides any field whose
    # name matches pk_attr from create/edit).
    form_include_pk = True
    identity = "process"
    icon = "fa fa-cogs"
    label = "Processes"
    name = "Process"

    fields = (
        StringField("identifier", label="Resource identifier"),
        StringField("version"),
        BooleanField("is_public"),
        StringField("title"),
        StringField("description"),
        DateTimeField("created_at"),
        DateTimeField("updated_at"),
        HasOne("owner", identity="user"),
        HasMany("editors", identity="user"),
        HasMany("viewers", identity="user"),
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
        ListField(CollectionField(name="inputs", fields=_INPUT_OUTPUT_FIELDS)),
        ListField(
            CollectionField(
                name="outputs",
                fields=(
                    *_INPUT_OUTPUT_FIELDS,
                    JSONField(name="data_classes"),
                    JSONField(name="data_access_apis"),
                ),
            )
        ),
        CollectionField(
            name="execution_unit",
            fields=(
                StringField(name="type_", label="Type"),
                StringField(name="image"),
                JSONField(name="bindings_inputs"),
                JSONField(name="bindings_outputs"),
                IntegerField(name="config_cpu_min_num"),
                IntegerField(name="config_cpu_max_num"),
                IntegerField(name="config_memory_min_gb"),
                IntegerField(name="config_memory_max_gb"),
                IntegerField(name="config_storage_temp_min_gb"),
                IntegerField(name="config_storage_outputs_min_gb"),
                IntegerField(name="config_job_timeout_seconds"),
                JSONField(name="definition"),
            ),
        ),
        JSONField("deployment_status"),
    )

    exclude_fields_from_list = (
        "description",
        "keywords",
        "additional_links",
        "inputs",
        "outputs",
        "execution_unit",
        "deployment_status",
        "editors",
        "viewers",
    )
    exclude_fields_from_create = (
        "created_at",
        "updated_at",
        "editors",
        "owner",
        "viewers",
        "deployment_status",
    )
    exclude_fields_from_edit = (
        "identifier",
        "created_at",
        "updated_at",
        "deployment_status",
    )

    async def is_row_action_allowed(self, request: Request, name: str) -> bool:
        if name in ("edit", "delete"):
            settings = cast("PottoSettings", request.app.state.SETTINGS)
            process_manager = settings.get_process_manager()
            capabilities = await process_manager.get_process_capabilities()

            if name == "edit" and not capabilities.supports_modification:
                return False
            if name == "delete" and not capabilities.supports_deletion:
                return False

            pk = request.path_params.get("pk")
            if pk is not None:
                user = cast(PottoUser, request.user)
                auth_backend = settings.get_authorization_backend()
                if (
                    process := await process_manager.get_process(
                        identifier=pk, user=user
                    )
                ) is not None:
                    return await auth_backend.can_edit_process(user, process)
        return await super().is_row_action_allowed(request, name)

    async def find_by_pk(self, request: Request, pk: Any) -> Any:
        user = cast(PottoUser, request.user)
        settings = cast("PottoSettings", request.app.state.SETTINGS)
        process_manager = settings.get_process_manager()
        auth_backend = settings.get_authorization_backend()
        process = await process_manager.get_process(pk, user)
        if process is None:
            return None
        if not await auth_backend.can_view_process(user, process):
            return None
        user_account_manager = settings.get_user_account_manager()
        editors = await user_account_manager.list_resource_editors(
            "process", process.identifier, user
        )
        viewers = await user_account_manager.list_resource_viewers(
            "process", process.identifier, user
        )
        object.__setattr__(process, "editors", editors)
        object.__setattr__(process, "viewers", viewers)
        return process

    async def find_by_pks(self, request: Request, pks: list[Any]) -> list[Any]:
        processes = [await self.find_by_pk(request, pk) for pk in pks]
        return [p for p in processes if p is not None]

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
        process_manager = settings.get_process_manager()
        page = (skip // limit) + 1
        processes, _ = await process_manager.paginated_list_processes(
            user,
            page=page,
            page_size=limit,
        )
        return processes

    async def count(self, request: Request, where: Any = None) -> int:
        user = cast(PottoUser, request.user)
        settings = cast("PottoSettings", request.app.state.SETTINGS)
        process_manager = settings.get_process_manager()
        _, total = await process_manager.paginated_list_processes(
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
            process_manager = settings.get_process_manager()
            capabilities = await process_manager.get_process_capabilities()
            can_edit = capabilities.supports_modification

            auth_backend = settings.get_authorization_backend()
            result["_meta"]["can_edit"] = can_edit and (
                await auth_backend.can_edit_process(user, obj)
            )
        return result

    async def serialize_field_value(
        self,
        value: Any,
        field: BaseField,
        action: RequestAction,
        request: Request,
    ) -> Any:
        if field.name == "execution_unit":
            return self._flatten_execution_unit(value)
        if field.name in ("inputs", "outputs"):
            return [dataclasses.asdict(item) for item in value]
        if field.name == "deployment_status":
            return dataclasses.asdict(value)
        else:
            return await super().serialize_field_value(value, field, action, request)

    def _flatten_execution_unit(self, value: Any) -> dict:
        if value is None:
            return {}
        if isinstance(value, ProcessExecutionUnitOci):
            return {
                "type_": "oci",
                "image": value.image,
                "bindings_inputs": {
                    # bindings_inputs/bindings_outputs hold plain dicts (not
                    # OciInputBinding/OciOutputBinding instances) - see
                    # Process.to_potto() in managers/postgis/db/models.py, which
                    # builds ProcessExecutionUnitOci straight from the stored
                    # JSONB dict without converting nested bindings.
                    k: _binding_to_camel_case(v)
                    for k, v in value.bindings_inputs.items()
                },
                "bindings_outputs": {
                    k: {"glob": v.get("glob_pattern")}
                    for k, v in value.bindings_outputs.items()
                },
                "config_cpu_min_num": value.config_cpu_min_num,
                "config_cpu_max_num": value.config_cpu_max_num,
                "config_memory_min_gb": value.config_memory_min_gb,
                "config_memory_max_gb": value.config_memory_max_gb,
                "config_storage_temp_min_gb": value.config_storage_temp_min_gb,
                "config_storage_outputs_min_gb": value.config_storage_outputs_min_gb,
                "config_job_timeout_seconds": value.config_job_timeout_seconds,
            }
        if isinstance(value, ProcessExecutionUnitCwl):
            return {"type_": "cwl", "definition": value.definition}
        if isinstance(value, ProcessExecutionUnitOther):
            return {"type_": value.type_, "definition": value.definition}
        return {}

    def _adapt_request_execution_unit_to_internal_model(self, data: dict) -> dict:
        """Admin form gets a flat dict covering all execution unit variants.

        This adapts it into the nested shape expected by ``ProcessCreate``/
        ``ProcessUpdate``'s discriminated ``execution_unit`` union.
        """
        type_ = data.get("type_") or "other"
        if type_ == "oci":
            return {
                "type_": "oci",
                "image": data.get("image"),
                "config": {
                    "cpuMin": data.get("config_cpu_min_num") or 1,
                    "cpuMax": data.get("config_cpu_max_num"),
                    "memoryMin": data.get("config_memory_min_gb"),
                    "memoryMax": data.get("config_memory_max_gb"),
                    "storageTempMin": data.get("config_storage_temp_min_gb"),
                    "storageOutputsMin": data.get("config_storage_outputs_min_gb"),
                    "jobTimeout": data.get("config_job_timeout_seconds"),
                },
                "bindings": {
                    "inputs": data.get("bindings_inputs") or {},
                    "outputs": data.get("bindings_outputs") or {},
                },
            }
        if type_ == "cwl":
            return {"type_": "cwl", "value": data.get("definition") or {}}
        return {"type_": type_, "value": data.get("definition") or {}}

    def _normalize_inputs_outputs(self, items: list[dict] | None) -> list[dict]:
        normalized = []
        for item in items or []:
            item = dict(item)
            max_occurs = str(item.get("max_occurs") or "").strip()
            item["max_occurs"] = max_occurs or "1"
            normalized.append(item)
        return normalized

    async def delete(self, request: Request, pks: list[Any]) -> int | None:
        user = cast(PottoUser, request.user)
        settings = cast("PottoSettings", request.app.state.SETTINGS)
        process_manager = settings.get_process_manager()
        capabilities = await process_manager.get_process_capabilities()

        if not capabilities.supports_deletion:
            return self.handle_exception(PottoException("Cannot delete process"))

        num_deleted = 0
        for pk in pks:
            try:
                await process_manager.delete_process(pk, user)
            except PottoException as err:
                return self.handle_exception(err)
            num_deleted += 1

        return num_deleted

    async def edit(self, request: Request, pk: Any, data: dict[str, Any]) -> Any:
        user = cast(PottoUser, request.user)
        settings = cast("PottoSettings", request.app.state.SETTINGS)
        process_manager = settings.get_process_manager()
        user_account_manager = settings.get_user_account_manager()

        execution_unit = self._adapt_request_execution_unit_to_internal_model(
            data.pop("execution_unit", None) or {}
        )
        inputs = self._normalize_inputs_outputs(data.pop("inputs", None))
        outputs = self._normalize_inputs_outputs(data.pop("outputs", None))
        new_editor_ids = set(data.pop("editors", None) or [])
        new_viewer_ids = set(data.pop("viewers", None) or [])
        data.pop("identifier", None)

        to_set = {
            **{k: v for k, v in data.items() if k != "owner"},
            "owner_id": data.get("owner"),
            "inputs": inputs,
            "outputs": outputs,
        }
        process_description = {k: v for k, v in to_set.items() if v is not None}

        process = await process_manager.get_process(pk, user)
        if process is None:
            raise PottoException(f"Process {pk} not found")
        try:
            updated = await process_manager.update_process(
                process,
                ProcessUpdate.model_validate(
                    {
                        "processDescription": process_description,
                        "execution_unit": execution_unit,
                    }
                ),
                user,
            )
        except (pydantic.ValidationError, PottoException) as err:
            return self.handle_exception(err)

        current_editors = await user_account_manager.list_resource_editors(
            "process", updated.identifier, user
        )
        current_viewers = await user_account_manager.list_resource_viewers(
            "process", updated.identifier, user
        )
        current_editor_ids = {e.id for e in current_editors}
        current_viewer_ids = {v.id for v in current_viewers}
        for target_user_id in (
            current_editor_ids | current_viewer_ids | new_editor_ids | new_viewer_ids
        ):
            if target_user_id in new_editor_ids:
                if target_user_id not in current_editor_ids:
                    await process_manager.grant_process_access(
                        granting_user=user,
                        target_user_id=target_user_id,
                        process=updated,
                        role="editor",
                    )
            elif target_user_id in new_viewer_ids:
                if target_user_id not in current_viewer_ids:
                    await process_manager.grant_process_access(
                        granting_user=user,
                        target_user_id=target_user_id,
                        process=updated,
                        role="viewer",
                    )
            else:
                await process_manager.revoke_process_access(
                    revoking_user=user,
                    target_user_id=target_user_id,
                    process=updated,
                )
        return updated

    async def create(self, request: Request, data: dict[str, Any]) -> Any:
        user = cast(PottoUser, request.user)
        settings = cast("PottoSettings", request.app.state.SETTINGS)
        process_manager = settings.get_process_manager()

        execution_unit = self._adapt_request_execution_unit_to_internal_model(
            data.pop("execution_unit", None) or {}
        )
        inputs = self._normalize_inputs_outputs(data.pop("inputs", None))
        outputs = self._normalize_inputs_outputs(data.pop("outputs", None))

        process_description = {
            "identifier": data.pop("identifier"),
            "title": data.pop("title"),
            "owner_id": user.id,
            "is_public": data.pop("is_public"),
            "version": data.pop("version"),
            "description": data.pop("description", None) or None,
            "keywords": data.pop("keywords", None) or None,
            "additional_links": data.pop("additional_links", None) or None,
            "inputs": inputs,
            "outputs": outputs,
        }
        try:
            return await process_manager.create_process(
                ProcessCreate.model_validate(
                    {
                        "processDescription": process_description,
                        "execution_unit": execution_unit,
                    }
                ),
                user,
            )
        except (pydantic.ValidationError, PottoException) as err:
            return self.handle_exception(err)
