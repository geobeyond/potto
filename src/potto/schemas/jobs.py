import dataclasses
import datetime as dt
import enum
from typing import (
    Any,
    Literal,
    Sequence,
)

import pydantic

from .auth import PottoUser
from .base import OgcApiException
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
    status: Literal["accepted", "running", "successful", "failed", "dismissed"]
    owner: PottoUser
    is_public: bool
    created_at: dt.datetime
    inputs: dict[str, Any] = dataclasses.field(default_factory=dict)
    outputs: dict[str, JobOutputDescription] = dataclasses.field(default_factory=dict)
    response_type: Literal["document", "raw"] = "raw"
    callback_uris: JobCallbackUris | None = None
    processingEntityType: Literal[
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
    ] | str = "ogc-api-processes"
    message: str | None = None
    exception: OgcApiException | None = None
    progress: int | None = None
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None
    additional_links: list[dict[str, str | dict[str, str]]] | None = None


class JobCreate(pydantic.BaseModel): ...


@dataclasses.dataclass(frozen=True)
class JobResultManagerCapabilities:
    supports_deletion: bool = False


@dataclasses.dataclass(frozen=True)
class JobResultFilter:
    identifiers: Sequence[str] | None = None


@dataclasses.dataclass(frozen=True)
class JobResult: ...
