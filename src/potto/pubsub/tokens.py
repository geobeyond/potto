"""Tokens used by external clients to authenticate with potto's public MQTT broker."""

import datetime as dt
import logging
from typing import (
    Any,
    TYPE_CHECKING,
)

import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from ..constants import (
    MQTT_TOKEN_AUDIENCE,
    MQTT_TOKEN_ISSUER,
)

if TYPE_CHECKING:
    from ..schemas.auth import PottoUser

logger = logging.getLogger(__name__)

_ALGORITHM = "EdDSA"


def parse_signing_key(pem: str) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
    except (TypeError, UnsupportedAlgorithm) as err:
        raise ValueError(str(err)) from err
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Not an Ed25519 private key")
    return key


def parse_public_key(pem: str) -> Ed25519PublicKey:
    try:
        key = serialization.load_pem_public_key(pem.encode())
    except UnsupportedAlgorithm as err:
        raise ValueError(str(err)) from err
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Not an Ed25519 public key")
    return key


def issue_mqtt_token(
    user: "PottoUser",
    signing_key: Ed25519PrivateKey,
    *,
    lifetime_minutes: int,
) -> tuple[str, dt.datetime]:
    """Issue a short-lived token for connecting to the public MQTT broker."""
    now = dt.datetime.now(dt.UTC)
    expires_at = now + dt.timedelta(minutes=lifetime_minutes)
    payload = {
        "iss": MQTT_TOKEN_ISSUER,
        "aud": MQTT_TOKEN_AUDIENCE,
        "sub": user.id,
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(payload, signing_key, algorithm=_ALGORITHM), expires_at


def verify_mqtt_token(token: str, public_key: Ed25519PublicKey) -> dict[str, Any]:
    """Verify an MQTT token and return its claims.

    Raises ``jwt.InvalidTokenError`` if the token is not valid.
    """
    return jwt.decode(
        token,
        public_key,
        algorithms=[_ALGORITHM],
        audience=MQTT_TOKEN_AUDIENCE,
        issuer=MQTT_TOKEN_ISSUER,
        options={"require": ["exp", "iat", "sub", "iss", "aud"]},
    )
