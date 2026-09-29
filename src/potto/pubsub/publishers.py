"""Publishers for potto's public MQTT broker."""

from faststream.mqtt import (
    MQTTBroker,
    QoS,
)

from ..constants import (
    PROCESS_EXTERNAL_PRIVATE_TOPIC_PREFIX,
    PROCESS_EXTERNAL_PUBLIC_TOPIC_PREFIX,
)
from ..schemas.events import (
    ExternalProcessEvent,
    ExternalPublishers,
)

PRIVATE_PROCESS_TOPIC_TEMPLATE = (
    f"{PROCESS_EXTERNAL_PRIVATE_TOPIC_PREFIX}/{{process_identifier}}/{{event_type}}"
)
PUBLIC_PROCESS_TOPIC_TEMPLATE = (
    f"{PROCESS_EXTERNAL_PUBLIC_TOPIC_PREFIX}/{{process_identifier}}/{{event_type}}"
)


def declare_external_publishers(broker: MQTTBroker) -> ExternalPublishers:
    """Register potto's publishers on a broker connected to the public broker.

    The topics given here are templates, used for the AsyncAPI document - each
    event is published with its actual topic (see ``topics.py``).
    """
    return ExternalPublishers(
        private_processes=broker.publisher(
            PRIVATE_PROCESS_TOPIC_TEMPLATE,
            qos=QoS.AT_LEAST_ONCE,
            schema=ExternalProcessEvent,
            title="private-process-events",
            description=(
                "Events on a private process, sent to each user who is allowed "
                "to view it."
            ),
        ),
        public_processes=broker.publisher(
            PUBLIC_PROCESS_TOPIC_TEMPLATE,
            qos=QoS.AT_LEAST_ONCE,
            schema=ExternalProcessEvent,
            title="public-process-events",
            description="Events on a public process.",
        ),
        # not published to yet, so left out of the AsyncAPI document
        private_collections=broker.publisher(
            "users/{user_id}/collections", include_in_schema=False
        ),
        private_jobs=broker.publisher("users/{user_id}/jobs", include_in_schema=False),
        public_collections=broker.publisher(
            "public/collections", include_in_schema=False
        ),
    )
