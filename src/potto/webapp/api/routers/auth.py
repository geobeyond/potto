import logging
from typing import Annotated

import bcrypt
import pydantic
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from fastapi.security import OAuth2PasswordRequestForm

from ....authn.jwt import create_access_token
from ....db.queries.auth import get_user_by_username
from ....schemas.auth import PottoUser
from ..dependencies import SettingsDependency

logger = logging.getLogger(__name__)
router = APIRouter()


class LoginResponse(pydantic.BaseModel):
    access_token: str
    token_type: str = "bearer"


# security: [{}] marks this as intentionally public; security: [] is treated the same
# as "undefined" by the OWASP spectral rule (check-security.js line 68).
@router.post("/login", name="login", openapi_extra={"security": [{}]})
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    settings: SettingsDependency,
) -> LoginResponse:
    """Authenticate with username and password, receive a JWT access token."""
    async with settings.get_db_session_maker()() as session:
        if (db_user := await get_user_by_username(session, form_data.username)) is None:
            logger.debug(f"Login failed: user {form_data.username!r} not found")
            raise HTTPException(status_code=401, detail="Invalid credentials")
    if not db_user.is_active:
        logger.warning(f"Login failed: user {form_data.username!r} is inactive")
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if db_user.hashed_password is None:
        logger.warning(
            f"Login failed: user {form_data.username!r} has no local password"
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not bcrypt.checkpw(
        form_data.password.encode(), db_user.hashed_password.encode()
    ):
        logger.debug(f"Login failed: wrong password for user {form_data.username!r}")
        raise HTTPException(status_code=401, detail="Invalid credentials")
    potto_user = PottoUser(
        id=db_user.id,
        username=db_user.username,
        email=db_user.email,
        is_active=db_user.is_active,
        scopes=db_user.scopes,
    )
    token = create_access_token(
        potto_user,
        settings.session_secret_key.get_secret_value(),
    )
    return LoginResponse(access_token=token)
