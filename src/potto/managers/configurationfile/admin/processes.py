import dataclasses
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
    CollectionField,
    DateTimeField,
    IntegerField,
    JSONField,
    ListField,
    StringField,
    URLField,
)

from ....schemas.auth import PottoUser
from ....schemas.processes import (
    ProcessExecutionUnitCwl,
    ProcessExecutionUnitOci,
    ProcessExecutionUnitOther,
)
from ....webapp.admin.views import _PottoAdminModelView

if TYPE_CHECKING:
    from ....config import PottoSettings

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
    """Read-only starlette-admin view for processes.

    The configuration-file manager never supports process mutations, so this view
    only ever offers list/search/view - create, edit and delete are all disabled.
    Field names below match ``potto.schemas.processes.Process`` (the schema returned
    by ``ProcessManagerProtocol``), since this view only ever works with schema
    instances.
    """

    pk_attr = "identifier"
    identity = "process_item"
    icon = "fa fa-cogs"
    label = "Processes"
    name = "Process"

    fields = (
        StringField("identifier", label="Resource identifier"),
        StringField("version"),
        BooleanField("is_public"),
        StringField("title"),
        StringField("description"),
        StringField("owner"),
        ListField(StringField("editors")),
        ListField(StringField("viewers")),
        DateTimeField("created_at"),
        DateTimeField("updated_at"),
        JSONField("keywords"),
        ListField(
            CollectionField(
                name="additional_links",
                fields=(
                    StringField(name="type", label="Media type"),
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
            "Creating processes is not supported by the configuration file manager."
        )

    async def edit(self, request: Request, pk: Any, data: dict[str, Any]) -> Any:
        raise NotImplementedError(
            "Editing processes is not supported by the configuration file manager."
        )

    async def delete(self, request: Request, pks: list[Any]) -> int | None:
        raise NotImplementedError(
            "Deleting processes is not supported by the configuration file manager."
        )

    async def find_by_pk(self, request: Request, pk: Any) -> Any:
        user = cast(PottoUser, request.user)
        settings = cast("PottoSettings", request.app.state.SETTINGS)
        process_manager = settings.get_process_manager()
        authorizer = settings.get_authorizer()
        process = await process_manager.get_process(pk, user)
        if process is None:
            return None
        if not await authorizer.can_view_process(user, process):
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
        if field.name == "execution_unit":
            return self._flatten_execution_unit(value)
        if field.name in ("inputs", "outputs"):
            return [dataclasses.asdict(item) for item in value]
        if field.name == "deployment_status":
            if value is None:
                return None
            status_dict = dataclasses.asdict(value)
            if status_dict["changed_at"] is not None:
                status_dict["changed_at"] = status_dict["changed_at"].isoformat()
            return status_dict
        return await super().serialize_field_value(value, field, action, request)

    def _flatten_execution_unit(self, value: Any) -> dict:
        if value is None:
            return {}
        if isinstance(value, ProcessExecutionUnitOci):
            return {
                "type_": "oci",
                "image": value.image,
                "bindings_inputs": {
                    k: _binding_to_camel_case(dataclasses.asdict(v))
                    for k, v in value.bindings_inputs.items()
                },
                "bindings_outputs": {
                    k: {"glob": v.glob_pattern}
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
