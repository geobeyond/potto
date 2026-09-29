import logging

from fastapi import (
    APIRouter,
    HTTPException,
)
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    Response,
)
from faststream.specification.asyncapi.site import get_asyncapi_html

from .. import responses
from ....constants import MediaType
from ....pubsub import tokens
from ....pubsub.asyncapi import build_asyncapi_document
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


@router.get("/pubsub/asyncapi.json", name="pubsub-asyncapi", include_in_schema=False)
async def get_asyncapi_json(settings: SettingsDependency) -> JSONResponse:
    """AsyncAPI document of potto's MQTT broker."""
    return JSONResponse(
        build_asyncapi_document(settings).to_jsonable(),
        media_type=MediaType.ASYNCAPI_JSON.value,
    )


@router.get(
    "/pubsub/asyncapi.yaml", name="pubsub-asyncapi-yaml", include_in_schema=False
)
async def get_asyncapi_yaml(settings: SettingsDependency) -> Response:
    """AsyncAPI document of potto's MQTT broker, as YAML."""
    return Response(
        build_asyncapi_document(settings).to_yaml(), media_type="application/yaml"
    )


@router.get("/pubsub/docs", name="pubsub-docs", include_in_schema=False)
async def get_asyncapi_docs(settings: SettingsDependency) -> HTMLResponse:
    """Interactive docs for potto's MQTT broker."""
    return HTMLResponse(
        get_asyncapi_html(
            build_asyncapi_document(settings),
            # clients cannot publish, so there is nothing to try out
            try_it_out_path=None,
        )
    )
