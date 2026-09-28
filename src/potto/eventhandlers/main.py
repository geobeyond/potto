import logging

from faststream import (
    ContextRepo,
    FastStream,
)
from faststream.mqtt import (
    MQTTRoute,
    MQTTRouter,
    QoS,
)

from ..config import PottoSettings
from ..constants import PROCESS_INTERNAL_TOPIC_PREFIX
from ..schemas.events import ExternalPublishers
from . import processes as process_handlers

logger = logging.getLogger(__name__)


def create_worker_app() -> FastStream:
    settings = PottoSettings()
    return create_worker_app_from_settings(settings)


def create_worker_app_from_settings(settings: "PottoSettings") -> FastStream:
    settings.external_mqtt_broker.validate_for("worker")
    internal_broker = settings.get_internal_broker(role="worker")
    internal_broker.include_router(
        MQTTRouter(
            # note: do not use the `prefix` parameter to MQTTRouter,
            # as it does not work together with shared subscriptions:
            # https://faststream.ag2.ai/latest/mqtt/shared/
            handlers=(
                MQTTRoute(
                    process_handlers.internal_handle_process_event,
                    "/".join(
                        (PROCESS_INTERNAL_TOPIC_PREFIX, "{identifier}/{event_type}")
                    ),
                    shared="process-lifecycle",
                    qos=QoS.AT_LEAST_ONCE,
                ),
                MQTTRoute(
                    process_handlers.bridge_internal_event_to_public,
                    "/".join(
                        (PROCESS_INTERNAL_TOPIC_PREFIX, "{identifier}/{event_type}")
                    ),
                    shared="bridge-to-public",
                    qos=QoS.AT_LEAST_ONCE,
                ),
            )
        )
    )
    external_broker = settings.get_external_broker()
    external_publishers = ExternalPublishers(
        private_collections=external_broker.publisher("users/{user_id}/collections"),
        private_processes=external_broker.publisher("users/{user_id}/processes"),
        private_jobs=external_broker.publisher("users/{user_id}/jobs"),
        public_collections=external_broker.publisher("public/collections"),
        public_processes=external_broker.publisher("public/processes"),
    )
    app = FastStream(internal_broker, external_broker)

    @app.on_startup
    async def initialize(context: ContextRepo):
        context.set_global("settings", settings)
        context.set_global("external_publishers", external_publishers)

    return app
