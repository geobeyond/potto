import asyncio
import contextlib
import dataclasses
import datetime as dt
import itertools
import socket
import types
from unittest import mock
from collections.abc import AsyncIterator

import jwt
import pytest
from amqtt.client import MQTTClient
from amqtt.contexts import (
    Action,
    BaseContext,
    ClientConfig,
)
from amqtt.errors import ConnectError
from amqtt.mqtt.constants import QOS_1
from amqtt.plugins.base import BasePlugin
from amqtt.session import Session

from pydantic import (
    SecretStr,
    TypeAdapter,
    ValidationError,
)

from potto import config
from potto.eventhandlers.main import create_worker_app_from_settings
from potto.exceptions import MissingConfigurationError
from potto.constants import EXTERNAL_BROKER_INTERNAL_LISTENER_NAME
from potto.eventhandlers import processes as process_handlers
from potto.eventhandlers.processes import bridge_internal_event_to_public
from potto.pubsub import tokens
from potto.pubsub.asyncapi import build_asyncapi_document
from potto.pubsub.broker import (
    PottoBroker,
    build_broker_config,
)
from potto.pubsub.publishers import (
    PRIVATE_PROCESS_TOPIC_TEMPLATE,
    PUBLIC_PROCESS_TOPIC_TEMPLATE,
)
from potto.pubsub.plugins import (
    EXPIRY_ATTRIBUTE,
    LISTENER_ATTRIBUTE,
    PottoTokenAuthPlugin,
    PottoTokenAuthPluginConfig,
    PottoTopicPlugin,
    ROLE_ATTRIBUTE,
    SUBJECT_ATTRIBUTE,
)
from potto.schemas.auth import (
    PottoUser,
    SystemPrincipal,
)
from potto.pubsub.topics import (
    private_process_topic,
    public_process_topic,
)
from potto.schemas.processes import (
    Process,
    ProcessDeploymentStatus,
    ProcessDeploymentStatusValue,
)
from potto.schemas.events import (
    AnyInternalProcessEvent,
    InternalProcessDeletionEvent,
    InternalProcessEvent,
    InternalProcessEventType,
    ResourceAudience,
)
from potto.webapp.main import create_app_from_settings
from pubsub_testing import (
    TEST_PUBSUB_PUBLIC_URL,
    generate_key_pair,
    get_session_key_pair,
)

PUBLISHER_PASSWORD = "test-publisher-password"


def _user(user_id: str = "user1") -> PottoUser:
    return PottoUser(id=user_id, username=f"name-{user_id}", is_active=True)


@pytest.fixture(scope="module")
def signing_key_pair() -> tuple[str, str]:
    # the same pair as the one configured in the ``settings`` fixture
    return get_session_key_pair()


@pytest.fixture
def signing_key(signing_key_pair):
    return tokens.parse_signing_key(signing_key_pair[0])


@pytest.fixture
def public_key(signing_key_pair):
    return tokens.parse_public_key(signing_key_pair[1])


def _issue(signing_key, user_id: str = "user1") -> str:
    token, _ = tokens.issue_mqtt_token(_user(user_id), signing_key, lifetime_minutes=15)
    return token


def _session(
    *,
    listener: str = "default",
    username: str | None = None,
    password: str | None = None,
) -> Session:
    session = Session()
    session.client_id = "a-client"
    session.username = username
    session.password = password
    session.attributes[LISTENER_ATTRIBUTE] = listener
    return session


@pytest.fixture
def auth_plugin(signing_key_pair) -> PottoTokenAuthPlugin:
    context = BaseContext()
    context.config = PottoTokenAuthPluginConfig(  # ty: ignore[invalid-assignment]
        publisher_password=PUBLISHER_PASSWORD,
        public_key=signing_key_pair[1],
    )
    return PottoTokenAuthPlugin(context)


@pytest.fixture
def topic_plugin() -> PottoTopicPlugin:
    context = BaseContext()
    # the topic plugin has no settings of its own
    context.config = BasePlugin.Config()  # ty: ignore[invalid-assignment]
    return PottoTopicPlugin(context)


def test_token_round_trip(signing_key, public_key):
    token = _issue(signing_key)
    claims = tokens.verify_mqtt_token(token, public_key)
    assert claims["sub"] == "user1"
    assert claims["iss"] == "potto"
    assert claims["aud"] == "potto-mqtt"
    assert "kid" not in jwt.get_unverified_header(token)


def test_token_signed_with_other_key_is_rejected(public_key):
    other_private_pem, _ = generate_key_pair()
    token = _issue(tokens.parse_signing_key(other_private_pem))
    with pytest.raises(jwt.InvalidTokenError):
        tokens.verify_mqtt_token(token, public_key)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"aud": "something-else"}, id="wrong-audience"),
        pytest.param({"iss": "someone-else"}, id="wrong-issuer"),
        pytest.param(
            {"exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)},
            id="expired",
        ),
    ],
)
def test_token_with_invalid_claims_is_rejected(signing_key, public_key, overrides):
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "iss": "potto",
        "aud": "potto-mqtt",
        "sub": "user1",
        "iat": now,
        "exp": now + dt.timedelta(minutes=15),
        **overrides,
    }
    token = jwt.encode(payload, signing_key, algorithm="EdDSA")
    with pytest.raises(jwt.InvalidTokenError):
        tokens.verify_mqtt_token(token, public_key)


def test_tampered_token_is_rejected(signing_key, public_key):
    header, payload, signature = _issue(signing_key).split(".")
    # the last base64url char of a 64-byte signature carries padding bits, so tamper with the first
    replacement = "B" if signature[0] == "A" else "A"
    tampered = ".".join((header, payload, replacement + signature[1:]))
    with pytest.raises(jwt.InvalidTokenError):
        tokens.verify_mqtt_token(tampered, public_key)


@pytest.mark.asyncio
async def test_anonymous_client_username_is_not_trusted(auth_plugin):
    session = _session(username="user1")
    assert await auth_plugin.authenticate(session=session) is True
    assert session.username is None
    assert session.attributes[SUBJECT_ATTRIBUTE] is None


@pytest.mark.asyncio
async def test_client_with_invalid_token_is_rejected(auth_plugin):
    session = _session(username="user1", password="not-a-token")
    assert await auth_plugin.authenticate(session=session) is False


@pytest.mark.asyncio
async def test_client_with_valid_token_gets_subject_as_username(
    auth_plugin, signing_key
):
    session = _session(username="whatever", password=_issue(signing_key, "user1"))
    assert await auth_plugin.authenticate(session=session) is True
    assert session.username == "user1"
    assert session.attributes[SUBJECT_ATTRIBUTE] == "user1"
    assert session.attributes[ROLE_ATTRIBUTE] == "client"


@pytest.mark.asyncio
async def test_persistent_session_cannot_be_resumed_by_another_identity(
    auth_plugin, signing_key
):
    session = _session(password=_issue(signing_key, "user1"))
    assert await auth_plugin.authenticate(session=session) is True
    session.password = _issue(signing_key, "user2")
    assert await auth_plugin.authenticate(session=session) is False
    session.password = None
    assert await auth_plugin.authenticate(session=session) is False


@pytest.mark.asyncio
async def test_publisher_is_accepted_on_internal_listener(auth_plugin):
    session = _session(
        listener=EXTERNAL_BROKER_INTERNAL_LISTENER_NAME, password=PUBLISHER_PASSWORD
    )
    assert await auth_plugin.authenticate(session=session) is True
    assert session.attributes[ROLE_ATTRIBUTE] == "publisher"


@pytest.mark.asyncio
@pytest.mark.parametrize("password", [None, "", "wrong-password", "token"])
async def test_internal_listener_rejects_non_publishers(
    auth_plugin, signing_key, password
):
    if password == "token":
        password = _issue(signing_key)
    session = _session(
        listener=EXTERNAL_BROKER_INTERNAL_LISTENER_NAME, password=password
    )
    assert await auth_plugin.authenticate(session=session) is False


@pytest.mark.asyncio
async def test_publisher_password_is_rejected_on_public_listener(auth_plugin):
    session = _session(password=PUBLISHER_PASSWORD)
    assert await auth_plugin.authenticate(session=session) is False


def _authenticated_session(
    role: str, subject: str | None = None, expiry: float | None = None
) -> Session:
    session = Session()
    session.attributes[ROLE_ATTRIBUTE] = role
    session.attributes[SUBJECT_ATTRIBUTE] = subject
    if expiry is not None:
        session.attributes[EXPIRY_ATTRIBUTE] = expiry
    return session


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role, subject, topic, action, expected",
    [
        ("publisher", None, "users/user1/processes/p/created", Action.PUBLISH, True),
        ("publisher", None, "#", Action.SUBSCRIBE, False),
        ("publisher", None, "public/processes/p/created", Action.RECEIVE, False),
        ("client", "user1", "users/user1/processes/p/created", Action.PUBLISH, False),
        ("client", None, "public/processes/p/created", Action.PUBLISH, False),
        ("client", None, "public/#", Action.SUBSCRIBE, True),
        ("client", None, "users/user1/#", Action.SUBSCRIBE, False),
        ("client", None, "#", Action.SUBSCRIBE, False),
        ("client", "user1", "users/user1/#", Action.SUBSCRIBE, True),
        ("client", "user1", "users/user1/processes/+/created", Action.SUBSCRIBE, True),
        ("client", "user1", "public/processes/#", Action.SUBSCRIBE, True),
        ("client", "user1", "users/user2/#", Action.SUBSCRIBE, False),
        ("client", "user1", "users/+/#", Action.SUBSCRIBE, False),
        ("client", "user1", "+/user1/#", Action.SUBSCRIBE, False),
        ("client", "user1", "#", Action.SUBSCRIBE, False),
        ("client", "user1", "users/user1", Action.SUBSCRIBE, False),
        ("client", "user1", "users/user1/processes/p/created", Action.RECEIVE, True),
        ("client", "user1", "users/user2/processes/p/created", Action.RECEIVE, False),
        (None, None, "public/#", Action.SUBSCRIBE, False),
    ],
)
async def test_topic_filtering(topic_plugin, role, subject, topic, action, expected):
    session = _authenticated_session(role, subject)
    result = await topic_plugin.topic_filtering(
        session=session, topic=topic, action=action
    )
    assert result is expected


@pytest.mark.asyncio
async def test_expired_session_does_not_receive(topic_plugin):
    expired = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
    session = _authenticated_session("client", "user1", expired.timestamp())
    result = await topic_plugin.topic_filtering(
        session=session,
        topic="users/user1/processes/p/created",
        action=Action.RECEIVE,
    )
    assert result is False


@dataclasses.dataclass
class _RecordingPublisher:
    published: list[tuple[str, dict]] = dataclasses.field(default_factory=list)

    async def publish(self, message, *, topic: str, **kwargs):
        self.published.append((topic, message.model_dump(mode="json")))


class _FakeProcessManager:
    def __init__(self, processes: dict):
        self._processes = processes

    async def get_process(self, identifier, user):
        return self._processes.get(identifier)


class _FakeUserAccountManager:
    def __init__(self, editors: list[str], viewers: list[str], inactive: set[str]):
        self._editors = editors
        self._viewers = viewers
        self._inactive = inactive

    def _users(self, user_ids: list[str]) -> list[PottoUser]:
        return [
            _user(i).model_copy(update={"is_active": i not in self._inactive})
            for i in user_ids
        ]

    async def list_resource_editors(self, resource_type, identifier, user):
        return self._users(self._editors)

    async def list_resource_viewers(self, resource_type, identifier, user):
        return self._users(self._viewers)


class _FakeAuthorizer:
    def __init__(self, denied: set[str]):
        self._denied = denied
        self.checked: list[str] = []

    async def can_view_process(self, principal, process) -> bool:
        self.checked.append(principal.id)
        return principal.id not in self._denied


def _fake_settings(
    processes: dict,
    editors=(),
    viewers=(),
    *,
    denied: set[str] | None = None,
    inactive: set[str] | None = None,
):
    process_manager = _FakeProcessManager(processes)
    user_account_manager = _FakeUserAccountManager(
        list(editors), list(viewers), inactive or set()
    )
    authorizer = _FakeAuthorizer(denied or set())
    return types.SimpleNamespace(
        public_url="http://potto.test",
        authorizer=authorizer,
        get_process_manager=lambda: process_manager,
        get_user_account_manager=lambda: user_account_manager,
        get_authorizer=lambda: authorizer,
    )


def _fake_publishers():
    return types.SimpleNamespace(
        public_processes=_RecordingPublisher(),
        private_processes=_RecordingPublisher(),
    )


def _process(identifier: str, *, is_public: bool, owner_id: str = "owner"):
    return types.SimpleNamespace(
        identifier=identifier, is_public=is_public, owner=_user(owner_id)
    )


def _event(
    event_type: InternalProcessEventType, identifier: str = "proc1"
) -> InternalProcessEvent:
    return InternalProcessEvent(
        event_type=event_type,
        process_identifier=identifier,
        initiated_by=SystemPrincipal("tests"),
        timestamp=dt.datetime.now(dt.timezone.utc),
        correlation_id="corr",
    )


def _snapshot(identifier: str = "proc1") -> Process:
    """A snapshot of a deleted process, as carried by its deletion event."""
    created_at = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    return Process(
        identifier=identifier,
        created_at=created_at,
        updated_at=created_at,
        title="Deleted process",
        owner=_user("owner"),
        is_public=False,
        version="1.0.0",
        deployment_status=ProcessDeploymentStatus(
            value=ProcessDeploymentStatusValue.FAILED
        ),
    )


def _deletion_event(
    audience: ResourceAudience, identifier: str = "proc1"
) -> InternalProcessDeletionEvent:
    return InternalProcessDeletionEvent(
        process_identifier=identifier,
        initiated_by=SystemPrincipal("tests"),
        timestamp=dt.datetime.now(dt.timezone.utc),
        correlation_id="corr",
        audience=audience,
        process=_snapshot(identifier),
    )


@pytest.mark.asyncio
async def test_bridge_publishes_public_process_event_once():
    settings = _fake_settings({"proc1": _process("proc1", is_public=True)})
    publishers = _fake_publishers()
    await bridge_internal_event_to_public(
        _event(InternalProcessEventType.CREATED), settings, publishers
    )
    assert [t for t, _ in publishers.public_processes.published] == [
        "public/processes/proc1/created"
    ]
    assert publishers.private_processes.published == []
    # public resources need no authorization decision
    assert settings.authorizer.checked == []
    payload = publishers.public_processes.published[0][1]
    assert payload["process_identifier"] == "proc1"
    assert payload["links"][0]["href"] == "http://potto.test/api/processes/proc1"


@pytest.mark.asyncio
async def test_bridge_publishes_private_process_event_to_each_user():
    settings = _fake_settings(
        {"proc1": _process("proc1", is_public=False, owner_id="owner")},
        editors=["editor", "owner"],
        viewers=["viewer", "bad/id"],
    )
    publishers = _fake_publishers()
    await bridge_internal_event_to_public(
        _event(InternalProcessEventType.UPDATED), settings, publishers
    )
    assert publishers.public_processes.published == []
    assert sorted(t for t, _ in publishers.private_processes.published) == [
        "users/editor/processes/proc1/updated",
        "users/owner/processes/proc1/updated",
        "users/viewer/processes/proc1/updated",
    ]


@pytest.mark.asyncio
async def test_bridge_only_publishes_to_users_allowed_by_authorizer():
    settings = _fake_settings(
        {"proc1": _process("proc1", is_public=False, owner_id="owner")},
        editors=["editor"],
        viewers=["viewer"],
        denied={"viewer"},
    )
    publishers = _fake_publishers()
    await bridge_internal_event_to_public(
        _event(InternalProcessEventType.UPDATED), settings, publishers
    )
    assert sorted(settings.authorizer.checked) == ["editor", "owner", "viewer"]
    assert sorted(t for t, _ in publishers.private_processes.published) == [
        "users/editor/processes/proc1/updated",
        "users/owner/processes/proc1/updated",
    ]


@pytest.mark.asyncio
async def test_bridge_skips_inactive_users():
    settings = _fake_settings(
        {"proc1": _process("proc1", is_public=False, owner_id="owner")},
        viewers=["viewer"],
        inactive={"viewer"},
    )
    publishers = _fake_publishers()
    await bridge_internal_event_to_public(
        _event(InternalProcessEventType.UPDATED), settings, publishers
    )
    assert [t for t, _ in publishers.private_processes.published] == [
        "users/owner/processes/proc1/updated"
    ]


@pytest.mark.asyncio
async def test_bridge_uses_the_audience_of_a_deletion_event():
    # a public process that has since been created with the same identifier must
    # not change who hears about the deletion of the old, private one
    settings = _fake_settings({"proc1": _process("proc1", is_public=True)})
    publishers = _fake_publishers()
    await bridge_internal_event_to_public(
        _deletion_event(ResourceAudience(is_public=False, user_ids=["owner"])),
        settings,
        publishers,
    )
    assert publishers.public_processes.published == []
    assert [t for t, _ in publishers.private_processes.published] == [
        "users/owner/processes/proc1/deleted"
    ]
    assert publishers.private_processes.published[0][1]["links"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event, processes",
    [
        pytest.param(_event(InternalProcessEventType.UPDATED), {}, id="process-gone"),
        pytest.param(
            _event(InternalProcessEventType.DEPLOYMENT_FAILED),
            {"proc1": _process("proc1", is_public=True)},
            id="internal-only",
        ),
    ],
)
async def test_bridge_does_not_publish(event, processes):
    settings = _fake_settings(processes)
    publishers = _fake_publishers()
    await bridge_internal_event_to_public(event, settings, publishers)
    assert publishers.public_processes.published == []
    assert publishers.private_processes.published == []


@pytest.mark.parametrize(
    "payload, expected",
    [
        pytest.param(
            {"event_type": "updated"}, InternalProcessEvent, id="non-deletion"
        ),
        pytest.param(
            {
                "event_type": "deleted",
                "audience": {"is_public": True},
                "process": _snapshot(),
            },
            InternalProcessDeletionEvent,
            id="deletion",
        ),
    ],
)
def test_internal_process_events_are_told_apart_by_type(payload, expected):
    event = TypeAdapter(AnyInternalProcessEvent).validate_python(
        {
            "process_identifier": "proc1",
            "initiated_by": {"name": "tests"},
            "timestamp": dt.datetime.now(dt.timezone.utc),
            "correlation_id": "corr",
            **payload,
        }
    )
    assert isinstance(event, expected)


def test_deletion_event_requires_an_audience():
    with pytest.raises(ValidationError):
        TypeAdapter(AnyInternalProcessEvent).validate_python(
            {
                "event_type": "deleted",
                "process_identifier": "proc1",
                "initiated_by": {"name": "tests"},
                "timestamp": dt.datetime.now(dt.timezone.utc),
                "correlation_id": "corr",
            }
        )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.asynccontextmanager
async def _running_broker(
    signing_key_pair: tuple[str, str],
) -> AsyncIterator[tuple[int, int, list[MQTTClient]]]:
    """Run a broker, yielding its (public port, internal port, clients to disconnect)."""
    public_port, internal_port = _free_port(), _free_port()
    settings = config.PottoSettings(
        external_mqtt_broker=config.ExternalMqttBrokerSettings(
            public_bind=f"127.0.0.1:{public_port}",
            internal_url=f"mqtt://127.0.0.1:{internal_port}",
            publisher_password=PUBLISHER_PASSWORD,
            token_public_key=signing_key_pair[1],
        ),
    )
    broker = PottoBroker(config=build_broker_config(settings))
    await broker.start()
    clients: list[MQTTClient] = []
    try:
        yield public_port, internal_port, clients
    finally:
        for client in clients:
            await client.disconnect()
        await broker.shutdown()


async def _connect_publisher(internal_port: int, clients: list[MQTTClient]):
    publisher = MQTTClient(client_id="publisher")
    await publisher.connect(
        f"mqtt://potto-publisher:{PUBLISHER_PASSWORD}@127.0.0.1:{internal_port}"
    )
    clients.append(publisher)
    return publisher


@pytest.mark.asyncio
async def test_broker_delivers_only_to_allowed_subscribers(signing_key_pair):
    signing_key = tokens.parse_signing_key(signing_key_pair[0])
    async with _running_broker(signing_key_pair) as (
        public_port,
        internal_port,
        clients,
    ):
        user1 = MQTTClient(client_id="user1-client")
        await user1.connect(
            f"mqtt://user1:{_issue(signing_key, 'user1')}@127.0.0.1:{public_port}"
        )
        user2 = MQTTClient(client_id="user2-client")
        await user2.connect(
            f"mqtt://user2:{_issue(signing_key, 'user2')}@127.0.0.1:{public_port}"
        )
        clients.extend((user1, user2))
        user1_sub = await user1.subscribe([("users/user1/#", QOS_1)])
        # attempting to snoop on everything is refused
        user2_sub = await user2.subscribe([("users/user2/#", QOS_1), ("#", QOS_1)])
        assert user1_sub == [QOS_1]
        assert user2_sub == [QOS_1, 0x80]

        intruder = MQTTClient(
            client_id="intruder", config=ClientConfig(auto_reconnect=False)
        )
        with pytest.raises(ConnectError):
            await intruder.connect(f"mqtt://127.0.0.1:{internal_port}")
        with pytest.raises(ConnectError):
            await intruder.connect(
                f"mqtt://potto-publisher:{PUBLISHER_PASSWORD}@127.0.0.1:{public_port}"
            )

        publisher = await _connect_publisher(internal_port, clients)
        await publisher.publish("users/user1/processes/p/created", b"hi", qos=QOS_1)

        message = await user1.deliver_message(timeout_duration=5)
        assert message is not None
        assert message.topic == "users/user1/processes/p/created"
        with pytest.raises(asyncio.TimeoutError):
            await user2.deliver_message(timeout_duration=0.5)


@pytest.mark.asyncio
async def test_broker_delivers_public_events_to_anonymous_subscribers(
    signing_key_pair,
):
    signing_key = tokens.parse_signing_key(signing_key_pair[0])
    async with _running_broker(signing_key_pair) as (
        public_port,
        internal_port,
        clients,
    ):
        anonymous = MQTTClient(client_id="anonymous-client")
        await anonymous.connect(f"mqtt://127.0.0.1:{public_port}")
        # a username without a password does not grant access to that user's topics
        impostor = MQTTClient(client_id="impostor-client")
        await impostor.connect(f"mqtt://user1@127.0.0.1:{public_port}")
        user1 = MQTTClient(client_id="user1-client")
        await user1.connect(
            f"mqtt://user1:{_issue(signing_key, 'user1')}@127.0.0.1:{public_port}"
        )
        clients.extend((anonymous, impostor, user1))

        assert await anonymous.subscribe(
            [("public/#", QOS_1), ("users/user1/#", QOS_1), ("#", QOS_1)]
        ) == [QOS_1, 0x80, 0x80]
        assert await impostor.subscribe([("users/user1/#", QOS_1)]) == [0x80]
        assert await user1.subscribe([("public/#", QOS_1)]) == [QOS_1]

        publisher = await _connect_publisher(internal_port, clients)
        await publisher.publish(
            "users/user1/processes/p/created", b"private", qos=QOS_1
        )
        await publisher.publish("public/processes/p/created", b"public", qos=QOS_1)

        # anonymous and authenticated subscribers both get the public event, and
        # the anonymous one never sees the private event published before it
        for client in (anonymous, user1):
            message = await client.deliver_message(timeout_duration=5)
            assert message is not None
            assert message.topic == "public/processes/p/created"
            assert message.data == b"public"
        with pytest.raises(asyncio.TimeoutError):
            await anonymous.deliver_message(timeout_duration=0.5)
        with pytest.raises(asyncio.TimeoutError):
            await impostor.deliver_message(timeout_duration=0.5)

        # anonymous clients may not publish, not even to public topics
        await anonymous.publish("public/processes/p/deleted", b"forged", qos=QOS_1)
        with pytest.raises(asyncio.TimeoutError):
            await user1.deliver_message(timeout_duration=0.5)


@pytest.mark.integration
def test_pubsub_token_requires_authentication(db, webapp_test_client):
    response = webapp_test_client.post("/api/pubsub/token")
    assert response.status_code == 401


@pytest.mark.integration
def test_pubsub_token_is_issued(
    settings, public_key, admin_user, webapp_test_client_as_admin
):
    response = webapp_test_client_as_admin.post("/api/pubsub/token")
    assert response.status_code == 200
    body = response.json()
    assert body["topic_prefix"] == f"users/{admin_user.id}/"
    assert body["public_topic_prefix"] == "public/"
    assert body["broker_url"] == TEST_PUBSUB_PUBLIC_URL
    claims = tokens.verify_mqtt_token(body["token"], public_key)
    assert claims["sub"] == admin_user.id


@pytest.mark.integration
def test_asyncapi_document_is_served(db, webapp_test_client):
    response = webapp_test_client.get("/api/pubsub/asyncapi.json")
    assert response.status_code == 200
    assert response.json()["servers"]["potto"]["host"] == "localhost:1884"
    response = webapp_test_client.get("/api/pubsub/asyncapi.yaml")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/yaml")
    response = webapp_test_client.get("/api/pubsub/docs")
    assert response.status_code == 200
    assert "private-process-events" in response.text


@pytest.mark.integration
def test_api_landing_page_links_to_asyncapi_document(db, webapp_test_client):
    links = webapp_test_client.get("/api/").json()["links"]
    service_descs = {li["type"]: li for li in links if li["rel"] == "service-desc"}
    assert set(service_descs) == {
        "application/vnd.oai.openapi+json;version=3.0",
        "application/asyncapi+json",
    }
    service_docs = [li["href"] for li in links if li["rel"] == "service-doc"]
    assert any(href.endswith("/api/pubsub/docs") for href in service_docs)
    response = webapp_test_client.get(
        service_descs["application/asyncapi+json"]["href"]
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/asyncapi+json"


def test_asyncapi_document_describes_only_the_public_broker():
    settings = config.PottoSettings(
        external_mqtt_broker=config.ExternalMqttBrokerSettings(
            internal_url="mqtt://internal-broker:1999",
            public_url="mqtt://broker.example.org:1884",
            publisher_password=PUBLISHER_PASSWORD,
        ),
    )
    document = build_asyncapi_document(settings).to_jsonable()
    assert list(document["servers"]) == ["potto"]
    assert document["servers"]["potto"]["host"] == "broker.example.org:1884"
    assert {channel["address"] for channel in document["channels"].values()} == {
        PRIVATE_PROCESS_TOPIC_TEMPLATE,
        PUBLIC_PROCESS_TOPIC_TEMPLATE,
    }
    assert {operation["action"] for operation in document["operations"].values()} == {
        "send"
    }
    assert "ExternalProcessEvent" in document["components"]["schemas"]
    private_channel = document["channels"]["private-process-events"]
    assert set(private_channel["parameters"]) == {
        "user_id",
        "process_identifier",
        "event_type",
    }
    serialized = build_asyncapi_document(settings).to_json()
    assert PUBLISHER_PASSWORD not in serialized
    assert "internal-broker" not in serialized


def test_asyncapi_topic_templates_match_published_topics():
    assert PRIVATE_PROCESS_TOPIC_TEMPLATE.format(
        user_id="u1", process_identifier="p1", event_type="created"
    ) == private_process_topic("u1", "p1", "created")
    assert PUBLIC_PROCESS_TOPIC_TEMPLATE.format(
        process_identifier="p1", event_type="created"
    ) == public_process_topic("p1", "created")


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"token_signing_key": "not-a-key"}, id="garbage-signing-key"),
        pytest.param(
            {"token_signing_key": generate_key_pair()[1]},
            id="public-key-as-signing-key",
        ),
        pytest.param({"token_public_key": "not-a-key"}, id="garbage-public-key"),
        pytest.param(
            {"token_public_key": generate_key_pair()[0]},
            id="private-key-as-public-key",
        ),
        pytest.param({"publisher_password": ""}, id="empty-publisher-password"),
        pytest.param({"internal_url": "mqtt://localhost"}, id="internal-url-no-port"),
    ],
)
def test_invalid_settings_are_rejected(overrides):
    with pytest.raises(ValidationError):
        config.ExternalMqttBrokerSettings(**overrides)


@pytest.mark.parametrize(
    "role, configured, missing",
    [
        pytest.param(
            "api", {"public_url": TEST_PUBSUB_PUBLIC_URL}, "TOKEN_SIGNING_KEY", id="api"
        ),
        pytest.param("worker", {}, "PUBLISHER_PASSWORD", id="worker"),
        pytest.param(
            "broker",
            {"publisher_password": PUBLISHER_PASSWORD},
            "TOKEN_PUBLIC_KEY",
            id="broker",
        ),
    ],
)
def test_each_process_requires_its_settings(role, configured, missing):
    broker_settings = config.ExternalMqttBrokerSettings(**configured)
    with pytest.raises(MissingConfigurationError, match=missing):
        broker_settings.validate_for(role)


def test_broker_does_not_use_the_signing_key(signing_key_pair):
    # the broker is only ever given the public key
    settings = config.PottoSettings(
        external_mqtt_broker=config.ExternalMqttBrokerSettings(
            publisher_password=PUBLISHER_PASSWORD,
            token_signing_key=SecretStr(signing_key_pair[0]),
        ),
    )
    with pytest.raises(MissingConfigurationError, match="TOKEN_PUBLIC_KEY"):
        build_broker_config(settings)


def test_webapp_requires_pubsub_settings(settings):
    settings.external_mqtt_broker.token_signing_key = None
    with pytest.raises(MissingConfigurationError, match="TOKEN_SIGNING_KEY"):
        create_app_from_settings(settings)


def _filters_overlap(first: str, second: str) -> bool:
    """Whether some topic would match both MQTT topic filters."""
    first_levels, second_levels = first.split("/"), second.split("/")
    for a, b in itertools.zip_longest(first_levels, second_levels):
        if a == "#" or b == "#":
            return True
        if a is None or b is None:
            return False
        if a != b and "+" not in (a, b):
            return False
    return True


def _without_share(topic: str) -> str:
    return topic.split("/", 2)[2] if topic.startswith("$share/") else topic


def test_worker_subscriptions_do_not_overlap():
    # faststream does not deliver a message to more than one subscriber of the same
    # broker connection when their topics overlap, even if they belong to
    # different shared subscription groups - one of them would silently get nothing
    settings = config.PottoSettings(
        external_mqtt_broker=config.ExternalMqttBrokerSettings(
            publisher_password=SecretStr("publisher-password")
        )
    )
    create_worker_app_from_settings(settings)
    topics = [
        _without_share(subscriber.topic)
        for subscriber in settings.get_internal_broker(role="worker").subscribers
    ]
    assert topics
    for first, second in itertools.combinations(topics, 2):
        assert not _filters_overlap(first, second), (first, second)


@pytest.mark.parametrize(
    "first, second, expected",
    [
        ("processes/+/+", "processes/+/+", True),
        ("processes/+/+", "processes/p1/created", True),
        ("processes/#", "processes/+/+", True),
        ("processes/+/+", "jobs/+/created", False),
        ("jobs/+/created", "jobs/+/deleted", False),
        ("processes/+", "processes/+/+", False),
    ],
)
def test_filters_overlap(first, second, expected):
    assert _filters_overlap(first, second) is expected


@pytest.mark.asyncio
async def test_process_event_handler_runs_both_steps_independently():
    event = _event(InternalProcessEventType.UPDATED)
    settings, publishers = object(), object()
    with (
        mock.patch.object(
            process_handlers,
            "internal_handle_process_event",
            side_effect=RuntimeError("reconciling failed"),
        ) as reconcile,
        mock.patch.object(
            process_handlers, "bridge_internal_event_to_public"
        ) as bridge,
    ):
        await process_handlers.handle_internal_process_event(
            event, settings, publishers
        )
    reconcile.assert_awaited_once_with(event, settings)
    bridge.assert_awaited_once_with(event, settings, publishers)


def test_worker_requires_publisher_password():
    settings = config.PottoSettings(
        external_mqtt_broker=config.ExternalMqttBrokerSettings(publisher_password=None)
    )
    with pytest.raises(MissingConfigurationError, match="PUBLISHER_PASSWORD"):
        create_worker_app_from_settings(settings)
