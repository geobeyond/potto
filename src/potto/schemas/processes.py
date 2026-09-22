import dataclasses
import datetime as dt
from typing import (
    Annotated,
    Any,
    Literal,
    Sequence,
)

import pydantic

from .auth import PottoUser
from .base import (
    MaybeDescription,
    MaybeKeywords,
    Title,
)


@dataclasses.dataclass(frozen=True)
class ProcessManagerCapabilities:
    supports_creation: bool = False
    supports_modification: bool = False
    supports_deletion: bool = False
    supports_granting_access: bool = False
    supports_revoking_access: bool = False


@dataclasses.dataclass(frozen=True)
class ProcessFilter:
    identifiers: Sequence[str] | None = None


@dataclasses.dataclass(frozen=True)
class ExecutionUnitRequirements:
    needs_remote_access: bool = False
    staging_mode: Literal["local-file", "remote-access"] = "local-file"


@dataclasses.dataclass(frozen=True)
class ProcessInputDescription:
    title: Title
    schema: dict
    min_occurs: int = 1
    max_occurs: int | Literal["unbounded"] = 1
    description: MaybeDescription = None
    keywords: MaybeKeywords = None


@dataclasses.dataclass(frozen=True)
class ProcessOutputDescription:
    title: Title
    schema: dict
    min_occurs: int = 1
    max_occurs: int | Literal["unbounded"] = 1
    description: MaybeDescription = None
    keywords: MaybeKeywords = None
    data_classes: list[str] | None = None
    data_access_apis: list[str] | None = None


@dataclasses.dataclass(frozen=True)
class ProcessExecutionUnit: ...


@dataclasses.dataclass(frozen=True)
class OciInputBinding:
    prefix: str | None = None
    position: int | str | None = None
    value_from: str | None = None
    item_separator: str | None = None
    shell_quote: bool = True


@dataclasses.dataclass(frozen=True)
class OciOutputBinding:
    glob_pattern: str | list[str] | None = None


@dataclasses.dataclass(frozen=True)
class ProcessExecutionUnitOci:
    image: str
    bindings_inputs: dict[str, OciInputBinding]
    bindings_outputs: dict[str, OciOutputBinding]
    type_: Literal["oci"] = "oci"
    config_cpu_min_num: int = 1
    config_cpu_max_num: int | None = None
    config_memory_min_gb: int | None = None
    config_memory_max_gb: int | None = None
    config_storage_temp_min_gb: int | None = None
    config_storage_outputs_min_gb: int | None = None
    config_job_timeout_seconds: int | None = None


@dataclasses.dataclass(frozen=True)
class ProcessExecutionUnitCwl:
    definition: dict[str, Any]
    type_: Literal["cwl"] = "cwl"


@dataclasses.dataclass(frozen=True)
class ProcessExecutionUnitOther:
    type_: str
    definition: dict[str, Any]


@dataclasses.dataclass(frozen=True)
class ProcessDeploymentStatus:
    value: Literal["queued", "in-progress", "deployed", "failed"]
    detail: str | None = None


@dataclasses.dataclass(frozen=True)
class Process:
    identifier: str
    created_at: dt.datetime
    updated_at: dt.datetime
    title: Title
    owner: PottoUser
    is_public: bool
    version: str
    deployment_status: ProcessDeploymentStatus
    execution_unit: (
        ProcessExecutionUnitOci
        | ProcessExecutionUnitCwl
        | ProcessExecutionUnitOther
        | None
    ) = None
    description: MaybeDescription = None
    keywords: MaybeKeywords = None
    additional_links: list[dict[str, str | dict[str, str]]] | None = None
    inputs: list[ProcessInputDescription] = dataclasses.field(default_factory=list)
    outputs: list[ProcessOutputDescription] = dataclasses.field(default_factory=list)


class ProcessDescriptionCreate(pydantic.BaseModel):
    identifier: str
    title: Title
    owner_id: str
    is_public: bool
    version: str
    description: MaybeDescription = None
    keywords: MaybeKeywords = None
    additional_links: list[dict[str, str | dict[str, str]]] | None = None
    inputs: Annotated[
        list[ProcessInputDescription], pydantic.Field(default_factory=list)
    ]
    outputs: Annotated[
        list[ProcessOutputDescription], pydantic.Field(default_factory=list)
    ]


class ProcessDescriptionUpdate(pydantic.BaseModel):
    owner_id: str | None = None
    title: Title | None = None
    is_public: bool | None = None
    version: str | None = None
    description: MaybeDescription = None
    keywords: MaybeKeywords = None
    additional_links: list[dict[str, str | dict[str, str]]] | None = None
    inputs: list[ProcessInputDescription] | None = None
    outputs: list[ProcessOutputDescription] | None = None


class ExecutionUnitOciConfigCreate(pydantic.BaseModel):
    cpu_min_num: Annotated[int, pydantic.Field(alias="cpuMin")] = 1
    cpu_max_num: Annotated[int | None, pydantic.Field(alias="cpuMax")] = None
    memory_min_gb: Annotated[int | None, pydantic.Field(alias="memoryMin")] = None
    memory_max_gb: Annotated[int | None, pydantic.Field(alias="memoryMax")] = None
    storage_temp_min_gb: Annotated[
        int | None, pydantic.Field(alias="storageTempMin")
    ] = None
    storage_outputs_min_gb: Annotated[
        int | None, pydantic.Field(alias="storageOutputsMin")
    ] = None
    job_timeout_seconds: Annotated[int | None, pydantic.Field(alias="jobTimeout")] = (
        None
    )


class ExecutionUnitOciConfigUpdate(pydantic.BaseModel):
    cpu_min_num: Annotated[int | None, pydantic.Field(alias="cpuMin")] = None
    cpu_max_num: Annotated[int | None, pydantic.Field(alias="cpuMax")] = None
    memory_min_gb: Annotated[int | None, pydantic.Field(alias="memoryMin")] = None
    memory_max_gb: Annotated[int | None, pydantic.Field(alias="memoryMax")] = None
    storage_temp_min_gb: Annotated[
        int | None, pydantic.Field(alias="storageTempMin")
    ] = None
    storage_outputs_min_gb: Annotated[
        int | None, pydantic.Field(alias="storageOutputsMin")
    ] = None
    job_timeout_seconds: Annotated[int | None, pydantic.Field(alias="jobTimeout")] = (
        None
    )


class OciInputBindingCreate(pydantic.BaseModel):
    prefix: str | None = None
    position: int | str | None = None
    value_from: Annotated[str | None, pydantic.Field(alias="valueFrom")] = None
    item_separator: Annotated[str | None, pydantic.Field(alias="itemSeparator")] = None
    shell_quote: Annotated[bool, pydantic.Field(alias="shellQuote")] = True


class OciInputBindingUpdate(pydantic.BaseModel):
    prefix: str | None = None
    position: int | str | None = None
    value_from: Annotated[str | None, pydantic.Field(alias="valueFrom")] = None
    item_separator: Annotated[str | None, pydantic.Field(alias="itemSeparator")] = None
    shell_quote: Annotated[bool | None, pydantic.Field(alias="shellQuote")] = None


class OciOutputBindingCreate(pydantic.BaseModel):
    glob_pattern: Annotated[str | list[str] | None, pydantic.Field(alias="glob")] = None


class OciBindingsCreate(pydantic.BaseModel):
    inputs: dict[str, OciInputBindingCreate]
    outputs: dict[str, OciOutputBindingCreate]


class OciBindingsUpdate(pydantic.BaseModel):
    inputs: dict[str, OciInputBindingUpdate] | None = None
    outputs: dict[str, OciOutputBindingCreate] | None = None


class ExecutionUnitOciCreate(pydantic.BaseModel):
    type_: Literal["oci"] = "oci"
    image: str
    config: ExecutionUnitOciConfigCreate
    bindings: OciBindingsCreate


class ExecutionUnitOciUpdate(pydantic.BaseModel):
    type_: Literal["oci"] = "oci"
    image: str | None = None
    config: ExecutionUnitOciConfigUpdate
    bindings: OciBindingsUpdate


class ExecutionUnitCwlCreate(pydantic.BaseModel):
    type_: Literal["cwl"] = "cwl"
    media_type: Literal["application/cwl"] = "application/cwl"
    value: dict[str, Any]


class ExecutionUnitCwlUpdate(pydantic.BaseModel):
    type_: Literal["cwl"] = "cwl"
    media_type: Literal["application/cwl"] | None = None
    value: dict[str, Any] | None = None


class ExecutionUnitOtherCreate(pydantic.BaseModel):
    type_: str
    value: dict[str, Any]


class ExecutionUnitOtherUpdate(pydantic.BaseModel):
    type_: str
    value: dict[str, Any] | None = None


def _execution_unit_type_tag(value: Any) -> str:
    type_ = (
        value.get("type_") if isinstance(value, dict) else getattr(value, "type_", None)
    )
    return type_ if type_ in ("oci", "cwl") else "other"


class ProcessCreate(pydantic.BaseModel):
    # this is an adaptation of the OgcApplicationPackage schema,
    # as outlined in oaproc-part2
    description: Annotated[
        ProcessDescriptionCreate, pydantic.Field(alias="processDescription")
    ]
    execution_unit: Annotated[
        Annotated[ExecutionUnitOciCreate, pydantic.Tag("oci")]
        | Annotated[ExecutionUnitCwlCreate, pydantic.Tag("cwl")]
        | Annotated[ExecutionUnitOtherCreate, pydantic.Tag("other")],
        pydantic.Discriminator(_execution_unit_type_tag),
    ]


class ProcessUpdate(pydantic.BaseModel):
    description: Annotated[
        ProcessDescriptionUpdate, pydantic.Field(alias="processDescription")
    ]
    execution_unit: Annotated[
        Annotated[ExecutionUnitOciUpdate, pydantic.Tag("oci")]
        | Annotated[ExecutionUnitCwlUpdate, pydantic.Tag("cwl")]
        | Annotated[ExecutionUnitOtherUpdate, pydantic.Tag("other")],
        pydantic.Discriminator(_execution_unit_type_tag),
    ]


class ProcessCreatedEvent(pydantic.BaseModel):
    identifier: str


class ProcessUpdatedEvent(pydantic.BaseModel):
    identifier: str
    old: dict


class ProcessDeletedEvent(pydantic.BaseModel):
    identifier: str
