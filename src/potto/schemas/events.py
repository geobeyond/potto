import dataclasses
import datetime as dt
import enum
from typing import (
    Annotated,
    Literal,
)

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


class ResourceAudience(pydantic.BaseModel):
    """Who is allowed to be notified about events on a resource."""

    is_public: bool
    user_ids: list[str] = pydantic.Field(default_factory=list)


class _BaseInternalProcessEvent(pydantic.BaseModel):
    process_identifier: str
    initiated_by: Principal
    timestamp: pydantic.AwareDatetime
    correlation_id: str


class InternalProcessEvent(_BaseInternalProcessEvent):
    """An event on a process that still exists - anything but its deletion."""

    event_type: Literal[
        InternalProcessEventType.CREATED,
        InternalProcessEventType.UPDATED,
        InternalProcessEventType.DEPLOYED,
        InternalProcessEventType.UNDEPLOYED,
        InternalProcessEventType.CREATION_FAILED,
        InternalProcessEventType.UPDATE_FAILED,
        InternalProcessEventType.DELETION_FAILED,
        InternalProcessEventType.DEPLOYMENT_FAILED,
        InternalProcessEventType.UNDEPLOYMENT_FAILED,
    ]


class InternalProcessDeletionEvent(_BaseInternalProcessEvent):
    """The deletion of a process.

    Since the process no longer exists, the event carries the audience that the
    process had, as resolved just before it was deleted.
    """

    event_type: Literal[InternalProcessEventType.DELETED] = (
        InternalProcessEventType.DELETED
    )
    audience: ResourceAudience


# Both kinds of event are published on the same topics, so consumers receive
# either one - ``event_type`` tells them apart
AnyInternalProcessEvent = Annotated[
    InternalProcessEvent | InternalProcessDeletionEvent,
    pydantic.Field(discriminator="event_type"),
]


class ExternalProcessEventType(enum.StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    DEPLOYED = "deployed"
    UNDEPLOYED = "undeployed"


class ExternalEventLink(pydantic.BaseModel):
    href: str
    rel: str
    type: str | None = None


class ExternalProcessEvent(pydantic.BaseModel):
    event_type: ExternalProcessEventType
    process_identifier: str
    timestamp: pydantic.AwareDatetime
    links: list[ExternalEventLink] = pydantic.Field(default_factory=list)


class PubSubTokenResponse(pydantic.BaseModel):
    token: str
    token_type: str = "mqtt"
    expires_at: dt.datetime
    username: str = pydantic.Field(
        description=(
            "Username to present when connecting to the broker. The broker "
            "derives the identity from the token, so this is informative only."
        )
    )
    topic_prefix: str
    public_topic_prefix: str
    broker_url: str
