"""potto's public MQTT broker, based on amqtt."""

from typing import (
    Any,
    TYPE_CHECKING,
)

from amqtt.broker import Broker
from amqtt.contexts import (
    BrokerConfig,
    ListenerConfig,
)
from amqtt.plugins.logging_amqtt import (
    EventLoggerPlugin,
    PacketLoggerPlugin,
)

from ..constants import EXTERNAL_BROKER_INTERNAL_LISTENER_NAME
from .plugins import (
    LISTENER_ATTRIBUTE,
    PottoTokenAuthPlugin,
    PottoTopicPlugin,
    get_plugin_path,
)

if TYPE_CHECKING:
    from ..config import PottoSettings


class PottoBroker(Broker):
    """An amqtt broker that lets plugins know which listener a session came from.

    amqtt does not pass the listener on to plugins, but potto's auth plugin needs
    it in order to only accept the publisher on the internal listener.

    NOTE: this overrides a private amqtt method (checked against amqtt 0.12.x).
    """

    async def _handle_client_session(
        self,
        reader: Any,
        writer: Any,
        client_session: Any,
        handler: Any,
        server: Any,
        listener_name: str,
    ) -> None:
        client_session.attributes[LISTENER_ATTRIBUTE] = listener_name
        await super()._handle_client_session(
            reader, writer, client_session, handler, server, listener_name
        )


def build_broker_config(settings: "PottoSettings") -> BrokerConfig:
    broker_settings = settings.external_mqtt_broker
    broker_settings.validate_for("broker")
    plugins: dict[str, dict[str, Any]] = {
        get_plugin_path(PottoTokenAuthPlugin): {
            "publisher_password": broker_settings.get_publisher_password(),
            "public_key": broker_settings.get_token_public_key(),
            "expiry_check_interval_seconds": broker_settings.expiry_check_interval_seconds,
        },
        get_plugin_path(PottoTopicPlugin): {},
        get_plugin_path(EventLoggerPlugin): {},
    }
    if settings.debug:
        plugins[get_plugin_path(PacketLoggerPlugin)] = {}
    config = BrokerConfig(
        listeners={
            "default": ListenerConfig(bind=broker_settings.public_bind),
            EXTERNAL_BROKER_INTERNAL_LISTENER_NAME: ListenerConfig(
                bind=f"0.0.0.0:{broker_settings.internal_url.port}"
            ),
        },
        plugins=plugins,
    )
    return config
