import logging

from fastapi import (
    APIRouter,
    HTTPException,
)

from .. import responses
from ....pubsub import tokens
from ....pubsub.topics import (
    private_topic_prefix,
    public_topic_prefix,
)
from ....schemas.events import PubSubTokenResponse
from ..dependencies import (
    SettingsDependency,
    UserDependency,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/pubsub/token",
    name="pubsub-token",
    responses=responses.ERROR_RESPONSES,
)
async def issue_pubsub_token(
    user: UserDependency,
    settings: SettingsDependency,
) -> PubSubTokenResponse:
    """Issue a short-lived token for subscribing to potto's MQTT broker.

    Send the token as the MQTT password when connecting to the broker.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    broker_settings = settings.external_mqtt_broker
    token, expires_at = tokens.issue_mqtt_token(
        user,
        broker_settings.get_token_signing_key(),
        lifetime_minutes=broker_settings.token_lifetime_minutes,
    )
    return PubSubTokenResponse(
        token=token,
        expires_at=expires_at,
        username=user.id,
        topic_prefix=private_topic_prefix(user.id),
        public_topic_prefix=public_topic_prefix(),
        broker_url=broker_settings.get_public_url(),
    )
