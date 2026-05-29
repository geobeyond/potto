import logging

import jwt
from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
)
from starlette.requests import HTTPConnection

from ..config import PottoSettings
from ..db.queries import auth as auth_queries
from ..schemas.auth import PottoUser
from .jwt import decode_access_token
from .oidc import OIDCProvider

logger = logging.getLogger(__name__)


class LocalAuthBackend(AuthenticationBackend):
    _settings: PottoSettings

    def __init__(self, settings: PottoSettings) -> None:
        self._settings = settings

    async def authenticate(
        self, conn: HTTPConnection
    ) -> tuple[AuthCredentials, PottoUser] | None:
        if user_id := conn.session.get("user_id"):
            logger.debug(f"{user_id=} found in the session")
            if (potto_user := await self._get_user_from_db(user_id)) is not None:
                return AuthCredentials(potto_user.scopes), potto_user
            logger.warning(
                f"Session contains user_id {user_id!r} but user not found or inactive"
            )
        # Try local HS256 Bearer JWT
        if (
            auth_header := conn.headers.get("Authorization")
        ) and auth_header.startswith("Bearer "):
            token = auth_header.rpartition(" ")[-1]
            try:
                payload = decode_access_token(
                    token,
                    self._settings.session_secret_key.get_secret_value(),
                )
            except jwt.InvalidTokenError:
                logger.warning(f"Was sent invalid token {token!r}")
                return None
            if (potto_user := await self._get_user_from_db(payload["sub"])) is not None:
                return AuthCredentials(potto_user.scopes), potto_user
            logger.warning(
                f"JWT contains sub {payload['sub']!r} but user not found or inactive"
            )

        return None

    async def _get_user_from_db(self, user_id: str) -> PottoUser | None:
        async with self._settings.get_db_session_maker()() as session:
            db_user = await auth_queries.get_user(session, user_id)
        if db_user is None:
            logger.debug(f"User {user_id!r} not found in database")
            return None
        if not db_user.is_active:
            logger.warning(f"User {db_user.username!r} is inactive, denying access")
            return None
        return db_user.to_potto()


class OIDCAuthBackend(AuthenticationBackend):
    _settings: PottoSettings
    _oidc_provider: OIDCProvider

    def __init__(self, settings: PottoSettings, oidc_provider: OIDCProvider) -> None:
        self._settings = settings
        self._oidc_provider = oidc_provider

    async def authenticate(
        self, conn: HTTPConnection
    ) -> tuple[AuthCredentials, PottoUser] | None:
        # Try session first (set during OIDC callback)
        if user_id := conn.session.get("user_id"):
            potto_user = await self._get_user_from_db(user_id)
            if potto_user is not None:
                return AuthCredentials(potto_user.scopes), potto_user
            logger.warning(
                f"Session contains user_id {user_id!r} but user not found or inactive"
            )

        # Try OIDC RS256 Bearer JWT
        if (
            auth_header := conn.headers.get("Authorization")
        ) and auth_header.startswith("Bearer "):
            token = auth_header.rpartition(" ")[-1]
            try:
                claims = await self._oidc_provider.validate_access_token(token)
            except jwt.InvalidTokenError:
                return None
            async with self._settings.get_db_session_maker()() as session:
                db_user = await auth_queries.get_user(session, claims["sub"])
                if db_user is None:
                    db_user = await self._oidc_provider.provision_user(session, claims)
            if not db_user.is_active:
                logger.warning(f"User {db_user.username!r} is inactive, denying access")
                return None
            # When roles_claim is configured, scopes come from the token directly
            scopes = self._oidc_provider.extract_scopes(claims) or db_user.scopes
            potto_user = PottoUser(
                id=db_user.id,
                username=db_user.username,
                email=db_user.email,
                is_active=db_user.is_active,
                scopes=scopes,
            )
            return AuthCredentials(potto_user.scopes), potto_user

        return None

    async def _get_user_from_db(self, user_id: str) -> PottoUser | None:
        async with self._settings.get_db_session_maker()() as session:
            db_user = await auth_queries.get_user(session, user_id)
        if db_user is None:
            logger.debug(f"User {user_id!r} not found in database")
            return None
        if not db_user.is_active:
            logger.warning(f"User {db_user.username!r} is inactive, denying access")
            return None
        return db_user.to_potto()
