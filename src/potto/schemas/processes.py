import dataclasses
import datetime as dt
from typing import (
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
class ProcessDeployment: ...


class ProcessDeploymentCreate(pydantic.BaseModel): ...


@dataclasses.dataclass(frozen=True)
class Process:
    identifier: str
    created_at: dt.datetime
    updated_at: dt.datetime
    title: Title
    owner: PottoUser
    is_public: bool
    version: str
    description: MaybeDescription = None
    keywords: MaybeKeywords = None
    custom_page_size: int | None = None
    custom_page_size_max: int | None = None
    additional_links: list[dict[str, str | dict[str, str]]] | None = None
    inputs: list[ProcessInputDescription] = dataclasses.field(default_factory=list)
    outputs: list[ProcessOutputDescription] = dataclasses.field(default_factory=list)
    deployment: ProcessDeployment | None = None


class ProcessCreate(pydantic.BaseModel): ...


class ProcessUpdate(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)
    owner_id: str | None = None
