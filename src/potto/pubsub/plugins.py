"""amqtt plugins that implement authentication and authorization for potto's public broker.

External clients authenticate by presenting a potto-issued MQTT token as their
password (or no password at all, for anonymous access) on the public listener.
They may only subscribe to ``public/...`` topics and to their own
``users/{user_id}/...`` topics, and they may never publish.

potto's worker authenticates on the internal listener with a shared secret and
is the only session allowed to publish.
"""

import asyncio
import contextlib
import dataclasses
import datetime as dt
import hmac
import logging
from typing import (
    Any,
    cast,
)

import jwt
from amqtt.broker import BrokerContext
from amqtt.contexts import (
    Action,
    BaseContext,
)
from amqtt.plugins.base import (
    BaseAuthPlugin,
    BasePlugin,
    BaseTopicPlugin,
)
from amqtt.session import Session
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..constants import EXTERNAL_BROKER_INTERNAL_LISTENER_NAME
from . import tokens
from .topics import (
    is_valid_topic_user_id,
    private_topic_prefix,
    public_topic_prefix,
)

logger = logging.getLogger(__name__)

# session attribute keys - the listener one is set by ``PottoBroker``
LISTENER_ATTRIBUTE = "potto_listener"
ROLE_ATTRIBUTE = "potto_role"
SUBJECT_ATTRIBUTE = "potto_sub"
EXPIRY_ATTRIBUTE = "potto_exp"
# set on the first successful authentication and kept for the lifetime of a
# persistent session, in order to prevent other identities from taking it over
OWNER_ATTRIBUTE = "potto_owner"

PUBLISHER_ROLE = "publisher"
CLIENT_ROLE = "client"
_ANONYMOUS_OWNER = "anonymous"


def _now_timestamp() -> float:
    return dt.datetime.now(dt.timezone.utc).timestamp()


def _is_expired(session: Session) -> bool:
    expiry = session.attributes.get(EXPIRY_ATTRIBUTE)
    return expiry is not None and expiry <= _now_timestamp()


@dataclasses.dataclass
class PottoTokenAuthPluginConfig:
    publisher_password: str
    # PEM-encoded Ed25519 public key for verifying tokens
    public_key: str
    expiry_check_interval_seconds: int = 10


class PottoTokenAuthPlugin(BaseAuthPlugin):
    # amqtt builds a plugin's config from the dataclass found in its ``Config``
    # attribute
    Config = PottoTokenAuthPluginConfig

    config: PottoTokenAuthPluginConfig
    _public_key: Ed25519PublicKey
    _expiry_task: asyncio.Task | None

    def __init__(self, context: BaseContext) -> None:
        super().__init__(context)
        self._public_key = tokens.parse_public_key(self.config.public_key)
        self._expiry_task: asyncio.Task | None = None

    async def authenticate(self, *, session: Session) -> bool | None:
        # always reset identity-related attributes, since persistent sessions are
        # reused across connections
        for attribute in (ROLE_ATTRIBUTE, SUBJECT_ATTRIBUTE, EXPIRY_ATTRIBUTE):
            session.attributes.pop(attribute, None)
        if session.attributes.get(LISTENER_ATTRIBUTE) == (
            EXTERNAL_BROKER_INTERNAL_LISTENER_NAME
        ):
            return self._authenticate_publisher(session)
        else:
            return self._authenticate_client(session)

    def _authenticate_publisher(self, session: Session) -> bool:
        if not session.password or not hmac.compare_digest(
            session.password.encode(), self.config.publisher_password.encode()
        ):
            logger.warning(
                f"Rejected connection from {session.client_id!r} on the internal "
                f"listener: invalid publisher credentials"
            )
            return False

        if not self._claim_session(session, owner=PUBLISHER_ROLE):
            return False

        session.attributes[ROLE_ATTRIBUTE] = PUBLISHER_ROLE
        return True

    def _authenticate_client(self, session: Session) -> bool:
        if not session.password:
            # anonymous - don't trust client-supplied username
            if not self._claim_session(session, owner=_ANONYMOUS_OWNER):
                return False

            session.username = None
            session.is_anonymous = True
            session.attributes[ROLE_ATTRIBUTE] = CLIENT_ROLE
            session.attributes[SUBJECT_ATTRIBUTE] = None
            return True

        try:
            claims = tokens.verify_mqtt_token(session.password, self._public_key)
        except jwt.InvalidTokenError as err:
            logger.info(f"Rejected MQTT token for {session.client_id!r}: {err}")
            return False

        subject = claims["sub"]
        if not is_valid_topic_user_id(subject):
            logger.warning(f"Rejected MQTT token with invalid subject {subject!r}")
            return False

        if not self._claim_session(session, owner=subject):
            return False

        session.username = subject
        session.is_anonymous = False
        session.attributes[ROLE_ATTRIBUTE] = CLIENT_ROLE
        session.attributes[SUBJECT_ATTRIBUTE] = subject
        session.attributes[EXPIRY_ATTRIBUTE] = float(claims["exp"])
        return True

    @staticmethod
    def _claim_session(session: Session, *, owner: str) -> bool:
        """Ensure a persistent session is only ever resumed by the same identity."""
        current_owner = session.attributes.setdefault(OWNER_ATTRIBUTE, owner)
        if current_owner != owner:
            logger.warning(
                f"Rejected connection: session {session.client_id!r} belongs to "
                f"another identity"
            )
            return False

        return True

    async def on_broker_post_start(self, *args: Any, **kwargs: Any) -> None:
        self._expiry_task = asyncio.create_task(self._disconnect_expired_sessions())

    async def on_broker_pre_shutdown(self, *args: Any, **kwargs: Any) -> None:
        if self._expiry_task is not None:
            self._expiry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._expiry_task
            self._expiry_task = None

    async def _disconnect_expired_sessions(self) -> None:
        # MQTT 3.1.1 has no re-authentication, so clients whose token expires
        # get disconnected and need to reconnect with a fresh token
        broker = cast(BrokerContext, self.context)._broker_instance
        while True:
            await asyncio.sleep(self.config.expiry_check_interval_seconds)
            for session, handler in list(broker.sessions.values()):
                if session.transitions.is_connected() and _is_expired(session):
                    logger.info(
                        f"Disconnecting {session.client_id!r}: MQTT token expired"
                    )
                    try:
                        await handler.handle_connection_closed()
                    except Exception:
                        logger.exception(
                            f"Failed to disconnect expired session "
                            f"{session.client_id!r}"
                        )


class PottoTopicPlugin(BaseTopicPlugin):
    async def topic_filtering(
        self,
        *,
        session: Session | None = None,
        topic: str | None = None,
        action: Action | None = None,
    ) -> bool | None:
        # amqtt treats ``None`` as a denial, so always return an explicit bool
        if session is None or topic is None or action is None:
            return False
        role = session.attributes.get(ROLE_ATTRIBUTE)
        if role == PUBLISHER_ROLE:
            return action == Action.PUBLISH
        if role != CLIENT_ROLE or action == Action.PUBLISH:
            return False
        if action == Action.RECEIVE and _is_expired(session):
            return False
        return is_topic_allowed_for_subject(
            topic, session.attributes.get(SUBJECT_ATTRIBUTE)
        )


def is_topic_allowed_for_subject(topic: str, subject: str | None) -> bool:
    """Check whether a client with the given subject may use the topic (filter).

    Checking by prefix rejects filters that would match beyond what is allowed,
    such as ``#``, ``+/...`` or ``users/+/...``.
    """
    allowed_prefixes = [public_topic_prefix()]
    if subject is not None and is_valid_topic_user_id(subject):
        allowed_prefixes.append(private_topic_prefix(subject))
    return any(topic.startswith(prefix) for prefix in allowed_prefixes)


def get_plugin_path(plugin: type[BasePlugin]) -> str:
    return f"{plugin.__module__}.{plugin.__qualname__}"
