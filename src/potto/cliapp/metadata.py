import asyncio
import inspect
import logging
import sys
from typing import (
    Annotated,
    Literal,
)

import cyclopts
from rich.table import Table

from ..config import (
    get_settings,
    PottoSettings,
)
from ..db.commands import metadata as metadata_commands
from ..operations import metadata as metadata_operations
from ..schemas.metadata import ServerMetadataFlattenedUpdate
from ..schemas import cli as cli_schemas

metadata_app = cyclopts.App()
logger = logging.getLogger(__name__)


@metadata_app.meta.default
def launcher(
    *tokens: Annotated[str, cyclopts.Parameter(show=False, allow_leading_hyphen=True)],
):
    """Manage server metadata."""
    command, bound, ignored = metadata_app.parse_args(tokens)
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


@metadata_app.command(name="detail")
async def get_metadata_detail(
    format: Literal["json", "table"] = "table",
    *,
    settings: Annotated[PottoSettings, cyclopts.Parameter(parse=False)],
):
    """Inspect current server metadata."""
    async with settings.get_db_session_maker()() as session:
        metadata = await metadata_operations.get_server_metadata(session)
    result = cli_schemas.ServerMetadataDetail.from_db_item(metadata)
    if format == "json":
        metadata_app.console.print_json(result.model_dump_json(indent=2))
    else:
        detail_table = _prepare_detail_table(result)
        metadata_app.console.print(detail_table)


@metadata_app.command(name="update")
async def update_metadata(
    to_update: Annotated[
        ServerMetadataFlattenedUpdate | None, cyclopts.Parameter(name="*")
    ] = None,
    format: Literal["json", "table"] = "table",
    *,
    settings: Annotated[PottoSettings, cyclopts.Parameter(parse=False)],
):
    """Update metadata"""
    if to_update is None:
        metadata_app.console.print("Nothing to update")
        sys.exit(0)
    async with settings.get_db_session_maker()() as session:
        metadata = await metadata_operations.get_server_metadata(session)
        updated_metadata = await metadata_commands.update_metadata_flattened(
            session, metadata, to_update
        )
    result = cli_schemas.ServerMetadataDetail.from_db_item(updated_metadata)
    if format == "json":
        metadata_app.console.print_json(result.model_dump_json(indent=2))
    else:
        detail_table = _prepare_detail_table(result)
        metadata_app.console.print(detail_table)


def _prepare_detail_table(instance: cli_schemas.ServerMetadataDetail):
    detail_table = Table(title="Server metadata")
    detail_table.add_column("property")
    detail_table.add_column("value")
    for field_name in instance.__class__.model_fields.keys():
        detail_table.add_row(field_name, str(getattr(instance, field_name)))
    return detail_table
