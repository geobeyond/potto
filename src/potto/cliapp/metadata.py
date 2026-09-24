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
from ..schemas.auth import SystemPrincipal
from ..schemas.metadata import (
    ServerMetadataFlattenedUpdate,
    unflatten_server_metadata_update,
)
from ..schemas import cli as cli_schemas
from ..util import run_sync

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
    metadata = await settings.get_server_metadata_manager().get_server_metadata()
    result = cli_schemas.ServerMetadataDetail.from_potto(metadata)
    if format == "json":
        metadata_app.console.print_json(result.model_dump_json(indent=2))
    else:
        detail_table = _prepare_detail_table(result)
        metadata_app.console.print(detail_table)


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
    server_metadata_manager = settings.get_server_metadata_manager()
    existing = await server_metadata_manager.get_server_metadata()
    nested_update = unflatten_server_metadata_update(existing, to_update)
    updated_metadata = await server_metadata_manager.update_server_metadata(
        nested_update, SystemPrincipal(name="cli")
    )
    result = cli_schemas.ServerMetadataDetail.from_potto(updated_metadata)
    if format == "json":
        metadata_app.console.print_json(result.model_dump_json(indent=2))
    else:
        detail_table = _prepare_detail_table(result)
        metadata_app.console.print(detail_table)


# Registering commands here (at import time, before `potto ...` parses argv) rather than
# inside `launcher()` is required for `--help` to reflect it: cyclopts resolves `--help`
# without ever invoking the meta.default launcher, at any nesting level.
_server_metadata_manager = get_settings().get_server_metadata_manager()
_server_metadata_capabilities = run_sync(
    _server_metadata_manager.get_server_metadata_capabilities()
)
if _server_metadata_capabilities.supports_modification:
    metadata_app.command(update_metadata, name="update")


def _prepare_detail_table(instance: cli_schemas.ServerMetadataDetail):
    detail_table = Table(title="Server metadata")
    detail_table.add_column("property")
    detail_table.add_column("value")
    for field_name in instance.__class__.model_fields.keys():
        detail_table.add_row(field_name, str(getattr(instance, field_name)))
    return detail_table
