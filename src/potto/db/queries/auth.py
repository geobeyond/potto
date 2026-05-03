from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from ...schemas.auth import PottoScope
from ..models import User
from .common import _get_total_num_records


async def collect_all_users(
    session: AsyncSession, admin_filter: bool = False
) -> list[User]:
    statement = select(User).order_by(User.username)
    if admin_filter:
        statement = statement.where(User.scopes.contains([PottoScope.ADMIN.value]))  # ty: ignore[unresolved-attribute]
    return list((await session.exec(statement)).all())


async def paginated_list_users(
    session: AsyncSession,
    *,
    admin_filter: bool = False,
    page: int = 1,
    page_size: int = 20,
    include_total: bool = False,
) -> tuple[list[User], int | None]:
    statement = select(User).order_by(User.username)
    offset = page_size * (page - 1)
    if admin_filter:
        statement = statement.where(User.scopes.contains([PottoScope.ADMIN.value]))  # ty: ignore[unresolved-attribute]
    items = (await session.exec(statement.offset(offset).limit(page_size))).all()
    num_total = (
        await _get_total_num_records(session, statement) if include_total else None
    )
    return list(items), num_total


async def get_user(
    session: AsyncSession,
    user_id: str,
) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_username(
    session: AsyncSession,
    username: str,
) -> User | None:
    statement = select(User).where(User.username == username)
    return (await session.exec(statement)).first()
