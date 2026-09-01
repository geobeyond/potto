import dataclasses
import logging
from typing import Literal

from .metadata import ServerMetadata
from .collections import CollectionList

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class HealthCheck:
    status: Literal["ok", "error"]
    database: Literal["ok", "outdated", "error"]


@dataclasses.dataclass(frozen=True)
class ConformanceDetail:
    conforms_to: list[str]


@dataclasses.dataclass(frozen=True)
class SystemOverview:
    metadata: ServerMetadata
    collections: CollectionList
    attribution: str | None = None
