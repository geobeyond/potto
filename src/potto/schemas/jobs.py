import dataclasses
from typing import Sequence

import pydantic


@dataclasses.dataclass(frozen=True)
class JobManagerCapabilities:
    supports_deletion: bool = False


@dataclasses.dataclass(frozen=True)
class JobFilter:
    identifiers: Sequence[str] | None = None


@dataclasses.dataclass(frozen=True)
class JobInputDescription: ...


@dataclasses.dataclass(frozen=True)
class JobOutputDescription: ...


@dataclasses.dataclass(frozen=True)
class JobStatus: ...


@dataclasses.dataclass(frozen=True)
class Job:
    status: JobStatus
    inputs: list[JobInputDescription] = dataclasses.field(default_factory=list)
    outputs: list[JobOutputDescription] = dataclasses.field(default_factory=list)


class JobCreate(pydantic.BaseModel): ...


@dataclasses.dataclass(frozen=True)
class JobResultManagerCapabilities:
    supports_deletion: bool = False


@dataclasses.dataclass(frozen=True)
class JobResultFilter:
    identifiers: Sequence[str] | None = None


@dataclasses.dataclass(frozen=True)
class JobResult: ...
