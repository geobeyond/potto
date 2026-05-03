import asyncio
import getpass
import inspect
import logging
from math import ceil
from rich.table import Table
from typing import (
    Annotated,
    Literal,
)

import cyclopts
import pydantic
from cyclopts.types import NonNegativeInt

from ..config import (
    get_settings,
    PottoSettings,
)
from ..db.commands import auth as auth_commands
from ..operations import auth as auth_ops
from ..schemas.auth import UserCreate
from ..schemas import cli as cli_schemas


user_app = cyclopts.App()
logger = logging.getLogger(__name__)


@user_app.meta.default
def launcher(
    *tokens: Annotated[str, cyclopts.Parameter(show=False, allow_leading_hyphen=True)],
):
    """User-related functionality."""
    command, bound, ignored = user_app.parse_args(tokens)
    additional_kwargs = {}
    if "settings" in ignored:
        additional_kwargs = {
            "settings": get_settings(),
        }
    if not inspect.iscoroutinefunction(command):
        return command(*bound.args, **bound.kwargs, **additional_kwargs)
    else:
        if bound is None:
            return asyncio.run(command(**additional_kwargs))
        else:
            return asyncio.run(
                command(*bound.args, **bound.kwargs, **additional_kwargs)
            )


@user_app.command(name="list")
async def list_users(
    page: NonNegativeInt = 1,
    page_size: NonNegativeInt = 20,
    format: Literal["json", "table"] = "table",
    *,
    settings: Annotated[PottoSettings, cyclopts.Parameter(parse=False)],
) -> None:
    """List existing users."""
    async with settings.get_db_session_maker()() as session:
        db_users, total = await auth_ops.paginated_list_users(
            session, page=page, page_size=page_size, include_total=True
        )
    assert total is not None
    result = cli_schemas.ItemList[cli_schemas.UserListItem](
        items=[cli_schemas.UserListItem.from_db_item(i) for i in db_users],
        meta=cli_schemas.ItemListMeta(
            page=page,
            page_size=len(db_users),
            total_items=total,
            total_pages=ceil(total / page_size),
        ),
    )
    if format == "json":
        user_app.console.print_json(result.model_dump_json(indent=2))
    else:
        user_table = Table(
            title="Users",
            caption=f"Showing {result.meta.page_size} of {result.meta.total_items} items",
        )
        for field_name in cli_schemas.UserListItem.model_fields.keys():
            user_table.add_column(field_name)
        for item_collection in result.items:
            table_row = []
            for field_name in cli_schemas.UserListItem.model_fields.keys():
                if field_name == "scopes":
                    table_row.append(", ".join(getattr(item_collection, field_name)))
                else:
                    table_row.append(str(getattr(item_collection, field_name)))
            user_table.add_row(*table_row)
        serialized = user_table
        user_app.console.print(serialized)


@user_app.command(name="create")
async def create_user(
    username: str,
    *,
    email: str | None = None,
    scope: list[str] | None = None,
    settings: Annotated[PottoSettings, cyclopts.Parameter(parse=False)],
) -> None:
    """Create a new user when using the local auth provider."""
    if settings.oidc is not None:
        raise SystemExit(
            "Error: user creation is not supported when using an OIDC auth "
            "provider. Users are provisioned automatically on first login."
        )
    password = getpass.getpass("Password (at least 8 characters): ")
    password_confirm = getpass.getpass("Confirm password: ")
    if password != password_confirm:
        raise SystemExit("Error: passwords do not match.")
    try:
        to_create = UserCreate(
            username=username,
            password=pydantic.SecretStr(password),
            email=email,
            scopes=scope or [],
        )
    except Exception as err:
        raise SystemExit(f"Error: {err}") from err
    async with settings.get_db_session_maker()() as session:
        db_user = await auth_commands.create_user(session, to_create)
    user_app.console.print(f"User {db_user.username!r} created (id: {db_user.id})")
