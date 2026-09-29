"""Topics used on potto's public MQTT broker."""

from ..constants import (
    EXTERNAL_PRIVATE_TOPIC_PREFIX,
    EXTERNAL_PUBLIC_TOPIC_PREFIX,
    PROCESS_EXTERNAL_PRIVATE_TOPIC_PREFIX,
    PROCESS_EXTERNAL_PUBLIC_TOPIC_PREFIX,
)

_FORBIDDEN_TOPIC_CHARACTERS = frozenset("/+#\x00")


def is_valid_topic_user_id(user_id: str | None) -> bool:
    """Check whether a user id can be used as a topic level.

    User ids are interpolated into topics, so they must not be empty nor
    contain MQTT topic separators or wildcards.
    """
    return bool(user_id) and not (_FORBIDDEN_TOPIC_CHARACTERS & set(user_id or ""))


def public_topic_prefix() -> str:
    return f"{EXTERNAL_PUBLIC_TOPIC_PREFIX}/"


def private_topic_prefix(user_id: str) -> str:
    return f"{EXTERNAL_PRIVATE_TOPIC_PREFIX.format(user_id=user_id)}/"


def public_process_topic(process_identifier: str, event_type: str) -> str:
    return "/".join(
        (PROCESS_EXTERNAL_PUBLIC_TOPIC_PREFIX, process_identifier, event_type)
    )


def private_process_topic(
    user_id: str, process_identifier: str, event_type: str
) -> str:
    return "/".join(
        (
            PROCESS_EXTERNAL_PRIVATE_TOPIC_PREFIX.format(user_id=user_id),
            process_identifier,
            event_type,
        )
    )
