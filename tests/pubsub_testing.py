"""Helpers for configuring potto's pubsub settings in tests."""

import functools

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

TEST_PUBSUB_PUBLIC_URL = "mqtt://localhost:1884"


def generate_key_pair() -> tuple[str, str]:
    """Generate an Ed25519 key pair, returned as (private PEM, public PEM)."""
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


@functools.cache
def get_session_key_pair() -> tuple[str, str]:
    """Return a key pair that stays the same for the whole test session."""
    return generate_key_pair()
