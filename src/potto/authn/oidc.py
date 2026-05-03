import logging
import time
from typing import (
    Any,
    cast,
)
from urllib.parse import urlencode

import httpx
import jwt
from sqlmodel.ext.asyncio.session import AsyncSession

from ..db.models import User
from ..db.commands import auth as auth_commands
from ..db.queries.auth import get_user
from ..schemas.auth import UserCreateFromOidc

logger = logging.getLogger(__name__)

_JWKS_CACHE_TTL = 3600  # seconds


class OIDCProvider:
    _access_token_audience: str | None
    _client_id: str
    _client_secret: str
    _discovery: dict | None
    _issuer: str
    _jwks: list[dict] | None
    _jwks_fetched_at: float
    _scopes: list[str]
    _roles_claim: str | None

    def __init__(
        self,
        issuer: str,
        client_id: str,
        client_secret: str,
        scopes: list[str],
        roles_claim: str | None,
        access_token_audience: str | None,
    ) -> None:
        self._issuer = issuer
        self._client_id = client_id
        self._client_secret = client_secret
        self._scopes = scopes
        self._roles_claim = roles_claim
        self._access_token_audience = access_token_audience
        self._discovery: dict | None = None
        self._jwks: list[dict] | None = None
        self._jwks_fetched_at: float = 0

    @property
    def issuer(self) -> str:
        return self._issuer

    async def get_discovery(self) -> dict:
        if self._discovery is None:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{self._issuer}/.well-known/openid-configuration")
                r.raise_for_status()
                self._discovery = r.json()
        return self._discovery

    async def _get_jwks(self) -> list[dict]:
        now = time.monotonic()
        if self._jwks is None or now - self._jwks_fetched_at > _JWKS_CACHE_TTL:
            discovery = await self.get_discovery()
            async with httpx.AsyncClient() as client:
                r = await client.get(discovery["jwks_uri"])
                r.raise_for_status()
                self._jwks = r.json().get("keys", [])
                self._jwks_fetched_at = now
        return self._jwks

    async def _find_signing_key(self, token: str) -> jwt.PyJWK:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        jwks = await self._get_jwks()
        if (key := _match_key(jwks, kid)) is None:
            # Possible key rotation – clear cache and retry once
            self._jwks = None
            jwks = await self._get_jwks()
            key = _match_key(jwks, kid)
        if key is None:
            raise jwt.InvalidTokenError(f"No JWKS key matching kid={kid!r}")
        return key

    def _decode_kwargs(self, audience: str | None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "algorithms": ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
            "issuer": self._issuer,
            "options": {"require": ["exp", "iss", "sub"]},
        }
        kwargs["options"] = cast(dict[str, Any], kwargs["options"])
        if audience is not None:
            kwargs["audience"] = audience
        else:
            kwargs["options"]["verify_aud"] = False
        return kwargs

    async def validate_id_token(self, token: str) -> dict:
        """Validate an OIDC ID token. Audience must be the client_id."""
        signing_key = await self._find_signing_key(token)
        return jwt.decode(
            token, signing_key.key, **self._decode_kwargs(self._client_id)
        )

    async def validate_access_token(self, token: str) -> dict:
        """Validate an OIDC JWT access token."""
        signing_key = await self._find_signing_key(token)
        return jwt.decode(
            token, signing_key.key, **self._decode_kwargs(self._access_token_audience)
        )

    def get_authorization_url(self, redirect_uri: str, state: str, nonce: str) -> str:
        if self._discovery is None:
            raise RuntimeError("OIDC discovery not loaded – call get_discovery() first")
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(self._scopes),
            "state": state,
            "nonce": nonce,
        }
        return f"{self._discovery['authorization_endpoint']}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        """Exchange an authorization code for tokens."""
        discovery = await self.get_discovery()
        async with httpx.AsyncClient() as client:
            r = await client.post(
                discovery["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
            r.raise_for_status()
            return r.json()

    async def get_userinfo(self, access_token: str) -> dict[str, Any]:
        """Fetch claims from the OIDC userinfo endpoint."""
        discovery = await self.get_discovery()
        async with httpx.AsyncClient() as client:
            r = await client.get(
                discovery["userinfo_endpoint"],
                headers={"Authorization": f"Bearer {access_token}"},
            )
            r.raise_for_status()
            return r.json()

    def extract_scopes(self, claims: dict) -> list[str]:
        """Extract potto scopes from token claims, or return empty list."""
        if self._roles_claim is None:
            return []
        # Support dot-notation for nested claims, e.g. "realm_access.roles"
        value: Any = claims
        for part in self._roles_claim.split("."):
            if not isinstance(value, dict):
                return []
            value = value.get(part)
            if value is None:
                return []
        if isinstance(value, list):
            return [str(r) for r in value if r]
        return []

    async def provision_user(self, session: AsyncSession, claims: dict) -> User:
        """Find or JIT-provision a local User from OIDC token claims."""
        sub = claims["sub"]
        if (db_user := await get_user(session, sub)) is not None:
            return db_user

        db_user = await auth_commands.provision_oidc_user(
            session,
            to_create=UserCreateFromOidc(
                id=sub,
                username=_derive_username(claims),
                is_active=True,
                scopes=self.extract_scopes(claims),
                email=claims.get("email"),
            ),
        )
        logger.info(f"JIT-provisioned OIDC user {db_user.username!r} (sub={sub!r})")
        return db_user


def _match_key(jwks: list[dict], kid: str | None) -> jwt.PyJWK | None:
    for key_data in jwks:
        if kid is None or key_data.get("kid") == kid:
            return jwt.PyJWK(key_data)
    return None


def _derive_username(claims: dict) -> str:
    candidate = claims.get("preferred_username") or claims.get("name") or ""
    # Strip @domain from email-style preferred_username
    if "@" in candidate:
        candidate = candidate.split("@")[0]
    # Keep alphanumeric, underscore, hyphen
    sanitized = "".join(c if c.isalnum() or c in "_-" else "_" for c in candidate)
    # Minimum length 5 – pad with part of sub
    if len(sanitized) < 5:
        sanitized = (sanitized + claims.get("sub", "").replace("-", ""))[:20]
    return sanitized[:20]
