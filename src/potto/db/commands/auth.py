import logging

import bcrypt
from sqlmodel.ext.asyncio.session import AsyncSession

from ...exceptions import PottoException
from ...schemas.auth import (
    UserCreate,
    UserCreateFromOidc,
    UserUpdate,
)
from ..models import User

logger = logging.getLogger(__name__)


async def provision_oidc_user(
    session: AsyncSession, to_create: UserCreateFromOidc
) -> User:
    instance = User.model_validate(to_create.model_dump())
    session.add(instance)
    await session.commit()
    await session.refresh(instance)
    return instance


async def create_user(session: AsyncSession, to_create: UserCreate) -> User:
    hashed = bcrypt.hashpw(
        to_create.password.get_secret_value().encode(), bcrypt.gensalt()
    )
    instance = User(
        username=to_create.username,
        email=to_create.email,
        hashed_password=hashed.decode(),
        is_active=to_create.is_active,
        scopes=to_create.scopes,
    )
    session.add(instance)
    await session.commit()
    await session.refresh(instance)
    return instance


async def update_user(
    session: AsyncSession,
    db_user: User,
    to_update: UserUpdate,
) -> User:
    updates = to_update.model_dump(exclude_unset=True)
    if "password" in updates:
        raw = updates.pop("password")
        if raw is not None:
            updates["hashed_password"] = bcrypt.hashpw(
                raw.encode(), bcrypt.gensalt()
            ).decode()
    for key, value in updates.items():
        setattr(db_user, key, value)
    session.add(db_user)
    await session.commit()
    await session.refresh(db_user)
    return db_user


async def delete_user(
    session: AsyncSession,
    user_id: str,
) -> None:
    if instance := (await session.get(User, user_id)):
        await session.delete(instance)
        await session.commit()
    else:
        raise PottoException(f"User with id {user_id} does not exist.")
