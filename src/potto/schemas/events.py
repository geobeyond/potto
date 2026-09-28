import dataclasses
import enum

import pydantic
from faststream.mqtt.publisher.usecase import MQTTPublisher

from .auth import Principal


@dataclasses.dataclass(frozen=True)
class ExternalPublishers:
    private_collections: MQTTPublisher
    private_jobs: MQTTPublisher
    private_processes: MQTTPublisher
    public_collections: MQTTPublisher
    public_processes: MQTTPublisher


class InternalProcessEventType(enum.StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    DEPLOYED = "deployed"
    UNDEPLOYED = "undeployed"
    CREATION_FAILED = "creation_failed"
    UPDATE_FAILED = "update_failed"
    DELETION_FAILED = "deletion_failed"
    DEPLOYMENT_FAILED = "deployment_failed"
    UNDEPLOYMENT_FAILED = "undeployment_failed"


class InternalProcessEvent(pydantic.BaseModel):
    event_type: InternalProcessEventType
    process_identifier: str
    initiated_by: Principal
    timestamp: pydantic.AwareDatetime
    correlation_id: str


class ExternalProcessEventType(enum.StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    DEPLOYED = "deployed"
    UNDEPLOYED = "undeployed"


class ExternalPrivateProcessEvent(pydantic.BaseModel):
    event_type: ExternalProcessEventType
    process_identifier: str
    timestamp: pydantic.AwareDatetime


class ExternalPublicProcessEvent(pydantic.BaseModel):
    event_type: ExternalProcessEventType
    process_identifier: str
    timestamp: pydantic.AwareDatetime
