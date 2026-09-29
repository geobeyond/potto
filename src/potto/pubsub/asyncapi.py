"""AsyncAPI document describing potto's public MQTT broker to its clients."""

import importlib.metadata
from typing import TYPE_CHECKING

from faststream.mqtt import MQTTBroker
from faststream.security import SASLPlaintext
from faststream.specification import AsyncAPI
from faststream.specification.asyncapi.v3_0_0.schema import ApplicationSchema

from ..schemas.events import ExternalProcessEventType
from .publishers import declare_external_publishers

if TYPE_CHECKING:
    from ..config import PottoSettings

SERVER_NAME = "potto"

_DESCRIPTION = """\
Notifications about changes to potto's resources, delivered over MQTT 3.1.1.

This document describes what potto *sends*, so each operation below is one that
clients subscribe to. Clients can never publish.

- Events on public resources are sent to `public/...` topics, and anyone may
  subscribe to them, including anonymous clients.
- Events on private resources are sent to `users/{user_id}/...` topics, once for
  each user who may view the resource. Only that user may subscribe to them.

Subscribe to `public/#` or `users/{user_id}/#` to receive every event you are
allowed to see. Events are delivered with QoS 1 (at least once), so the same
event may be received more than once.

Events are thin: they identify the resource and link to it. Fetch the resource
through potto's API in order to get its full representation.
"""

_SECURITY_DESCRIPTION = """\
Connect without a password to subscribe to public topics only.

In order to subscribe to your private topics, call `POST /api/pubsub/token` on
potto's API and send the returned token as the MQTT password. The broker takes
your identity from the token, so the username is ignored. Tokens are short-lived:
the broker disconnects clients whose token has expired, so get a new token and
reconnect.
"""

_CHANNEL_PARAMETERS = {
    "user_id": {
        "description": (
            "The id of the user who receives the event, as returned in the "
            "`username` of the `POST /api/pubsub/token` response."
        ),
    },
    "process_identifier": {"description": "The identifier of the process."},
    "event_type": {
        "description": "What happened to the resource.",
        "enum": [event_type.value for event_type in ExternalProcessEventType],
    },
}


def build_asyncapi_document(settings: "PottoSettings") -> ApplicationSchema:
    """Build the AsyncAPI document of potto's public broker.

    The document is generated from a broker that is never connected: it
    describes the public listener that clients connect to, and has none of
    the credentials that potto uses for publishing.
    """
    broker = MQTTBroker(
        specification_url=settings.external_mqtt_broker.get_public_url(),
        version="3.1.1",
        security=SASLPlaintext(username="", password=""),
        description="potto's public MQTT broker.",
    )
    declare_external_publishers(broker)
    document = AsyncAPI(
        broker,
        title="potto events",
        version=importlib.metadata.version("potto"),
        description=_DESCRIPTION,
        schema_version="3.0.0",
    ).to_specification()
    # schema version 3.0.0 always gives an ApplicationSchema
    assert isinstance(document, ApplicationSchema)
    _rename_server(document)
    for channel in document.channels.values():
        if parameters := {
            name: definition
            for name, definition in _CHANNEL_PARAMETERS.items()
            if f"{{{name}}}" in (channel.address or "")
        }:
            # FastStream's Channel does not declare parameters, but allows extra fields
            channel.parameters = parameters  # ty: ignore[unresolved-attribute]
    if document.components is not None:
        for scheme in (document.components.securitySchemes or {}).values():
            scheme["description"] = _SECURITY_DESCRIPTION
    return document


def _rename_server(document: ApplicationSchema) -> None:
    document.servers = {
        SERVER_NAME: server for server in (document.servers or {}).values()
    }
    for channel in document.channels.values():
        channel.servers = [{"$ref": f"#/servers/{SERVER_NAME}"}]
