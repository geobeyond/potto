import dataclasses
import datetime as dt
import enum
from typing import (
    Annotated,
    Any,
    Literal,
    Sequence,
)

import pydantic

from .auth import PottoUser
from .base import OgcApiException
from .pagination import Pagination
from .processes import Process


class JobStatus(enum.StrEnum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    SUCCESSFUL = "successful"
    FAILED = "failed"
    DISMISSED = "dismissed"


@dataclasses.dataclass(frozen=True)
class JobManagerCapabilities:
    supports_deployment: bool = False
    supports_undeployment: bool = False
    supports_deletion: bool = False


@dataclasses.dataclass(frozen=True)
class JobFilter:
    identifiers: Sequence[str] | None = None


@dataclasses.dataclass(frozen=True)
class JobOutputFormat:
    media_type: str | None = None
    encoding: str | None = None
    schema: str | dict[str, Any] | None = None


@dataclasses.dataclass(frozen=True)
class JobOutputDescription:
    format_: str | None = None
    transmission_mode: Literal["value", "reference"] = "value"


@dataclasses.dataclass(frozen=True)
class JobCallbackUris:
    success_uri: str
    in_progress_uri: str | None = None
    failed_uri: str | None = None


@dataclasses.dataclass(frozen=True)
class Job:
    identifier: str
    process: Process
    status: JobStatus
    owner: PottoUser
    is_public: bool
    created_at: dt.datetime
    inputs: dict[str, Any] = dataclasses.field(default_factory=dict)
    outputs: dict[str, JobOutputDescription] = dataclasses.field(default_factory=dict)
    response_type: Literal["document", "raw"] = "raw"
    callback_uris: JobCallbackUris | None = None
    processingEntityType: (
        Literal[
            "ogc-api-processes",
            "openeo",
            "ogc-api-features",
            "ogc-api-coverages",
            "ogc-api-edr",
            "ogc-api-tiles",
            "ogc-api-moving-features",
            "ogc-api-sensor-things",
            "ogc-api-records",
            "ogc-api-dggs",
            "stac-api",
        ]
        | str
    ) = "ogc-api-processes"
    message: str | None = None
    exception: OgcApiException | None = None
    progress: int | None = None
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None
    additional_links: list[dict[str, str | dict[str, str]]] | None = None


@dataclasses.dataclass(frozen=True)
class JobList:
    jobs: list[Job]
    pagination: Pagination


class JobOutputCreate(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(populate_by_name=True)

    format_: Annotated[str | None, pydantic.Field(alias="format")] = None
    transmission_mode: Annotated[
        Literal["value", "reference"], pydantic.Field(alias="transmissionMode")
    ] = "value"


class JobSubscriberCreate(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(populate_by_name=True)

    success_uri: Annotated[str, pydantic.Field(alias="successUri")]
    in_progress_uri: Annotated[str | None, pydantic.Field(alias="inProgressUri")] = None
    failed_uri: Annotated[str | None, pydantic.Field(alias="failedUri")] = None


class JobCreate(pydantic.BaseModel):
    """A request to execute a process, as per OGC API - Processes execute requests.

    The identifier of the process to execute is not part of the request body and
    is thus passed separately to the job manager.
    """

    inputs: dict[str, Any] = pydantic.Field(default_factory=dict)
    outputs: dict[str, JobOutputCreate] = pydantic.Field(default_factory=dict)
    response: Literal["raw", "document"] = "raw"
    subscriber: JobSubscriberCreate | None = None


@dataclasses.dataclass(frozen=True)
class JobResultManagerCapabilities:
    supports_deletion: bool = False


@dataclasses.dataclass(frozen=True)
class JobResultFilter:
    identifiers: Sequence[str] | None = None


@dataclasses.dataclass(frozen=True)
class JobResult: ...
