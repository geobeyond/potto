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
from . import processes as process_handlers

logger = logging.getLogger(__name__)


def create_worker_app() -> FastStream:
    settings = PottoSettings()
    return create_worker_app_from_settings(settings)


def create_worker_app_from_settings(settings: "PottoSettings") -> FastStream:
    internal_broker = settings.get_internal_broker(role="worker")
    internal_broker.include_router(
        MQTTRouter(
            # note: do not use the `prefix` parameter to MQTTRouter,
            # as it does not work together with shared subscriptions:
            # https://faststream.ag2.ai/latest/mqtt/shared/
            handlers=(
                MQTTRoute(
                    process_handlers.handle_process_event,
                    "/".join(
                        (PROCESS_INTERNAL_TOPIC_PREFIX, "{identifier}/{event_type}")
                    ),
                    shared="process-lifecycle",
                    qos=QoS.AT_LEAST_ONCE,
                ),
            )
        )
    )
    app = FastStream(internal_broker)

    @app.on_startup
    async def initialize(context: ContextRepo):
        context.set_global("settings", settings)

    return app
