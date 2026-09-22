import logging

from faststream import (
    ContextRepo,
    FastStream,
)
from faststream.mqtt import (
    MQTTBroker,
    MQTTRoute,
    MQTTRouter,
)

from ..config import PottoSettings
from . import processes as process_handlers

logger = logging.getLogger(__name__)


def create_app_from_settings(settings: "PottoSettings") -> FastStream:
    internal_broker = MQTTBroker(url=settings.internal_mqtt_broker.url.unicode_string())
    internal_broker.include_router(
        MQTTRouter(
            handlers=(
                MQTTRoute(
                    process_handlers.handle_process_created,
                    "processes/{identifier}/created",
                ),
                MQTTRoute(
                    process_handlers.handle_process_updated,
                    "processes/{identifier}/updated",
                ),
                MQTTRoute(
                    process_handlers.handle_process_deleted,
                    "processes/{identifier}/deleted",
                ),
            )
        )
    )
    app = FastStream(internal_broker)

    @app.on_startup
    async def initialize(context: ContextRepo):
        context.set_global("settings", settings)

    return app
