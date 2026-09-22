import asyncio
import inspect
import logging
import logging.config
import os
import sys
from pathlib import Path
from typing import Annotated

import cyclopts
import yaml
from cyclopts import App
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.traceback import install as rich_install_traceback

from ..config import (
    get_settings,
    PottoSettings,
)

from .banner import BANNER
from .cite import cite_app
from .collections import collections_app
from .dev import dev_app
from .metadata import metadata_app
from .openapi import app as openapi_app
from .users import user_app

_console = Console()
_error_console = Console(stderr=True)
potto_app = App(
    console=_console,
    error_console=_error_console,
)
rich_install_traceback(console=_error_console)
cite_app.console = _console
cite_app.error_console = _error_console
collections_app.console = _console
collections_app.error_console = _error_console
dev_app.console = _console
dev_app.error_console = _error_console
metadata_app.console = _console
metadata_app.error_console = _error_console
openapi_app.console = _console
openapi_app.error_console = _error_console
user_app.console = _console
user_app.error_console = _error_console

potto_app.command(collections_app.meta, name="collection")
potto_app.command(dev_app.meta, name="dev")
potto_app.command(metadata_app.meta, name="metadata")
potto_app.command(user_app.meta, name="user")
potto_app.command(cite_app.meta, name="cite-testing")
potto_app.command(openapi_app.meta, name="openapi")


async def _register_manager_cli_groups(settings: PottoSettings) -> None:
    """Register each configured manager's own CLI commands under its own group.

    Constructing the managers here also validates their settings_model dicts
    eagerly, so a misconfigured manager fails fast on any ``potto ...``
    invocation rather than deep inside whatever command first happens to touch
    it. Managers are deduped by potto_cli_group name since, in the default
    all-postgis deployment, all three protocol getters return the same cached
    PostgisManager instance.
    """
    cli_groups: dict[str, cyclopts.App] = {}
    seen_group_names: set[str] = set()
    for manager in (
        settings.get_collection_manager(),
        settings.get_server_metadata_manager(),
        settings.get_user_account_manager(),
    ):
        if manager.potto_cli_group in seen_group_names:
            continue
        seen_group_names.add(manager.potto_cli_group)
        if (group := await manager.get_cli_group()) is not None:
            cli_groups[manager.potto_cli_group] = group
    for name, group in cli_groups.items():
        group.console = potto_app.console
        group.error_console = potto_app.error_console
        potto_app.command(group, name=name)


@potto_app.meta.default
def launcher(
    *tokens: Annotated[str, cyclopts.Parameter(show=False, allow_leading_hyphen=True)],
):
    """Potto, the OGC API server."""
    # Custom cli launcher that injects potto's settings if needed.

    # This custom launcher detects if access to the potto settings is
    # being requested by the underlying CLI command and injects them if needed.

    # Note that this strategy is used because we do not use cyclopts builtin
    # configuration facilities, but rather pydantic-settings.
    settings = get_settings()
    rich_log_handler = RichHandler(console=potto_app.error_console)
    if (
        log_config_file := settings.uvicorn_log_config_file
    ) and log_config_file.exists():
        log_config = yaml.safe_load(settings.uvicorn_log_config_file.read_text())
        logging.config.dictConfig(log_config)
    else:
        logging.basicConfig(
            level=logging.DEBUG if settings.debug else logging.INFO,
            handlers=[rich_log_handler],
        )
    asyncio.run(_register_manager_cli_groups(settings))
    command, bound, ignored = potto_app.parse_args(tokens)
    additional_kwargs = {}
    if "settings" in ignored:
        additional_kwargs = {
            "settings": settings,
        }
    if inspect.iscoroutinefunction(command):
        return asyncio.run(command(*bound.args, **bound.kwargs, **additional_kwargs))
    return command(*bound.args, **bound.kwargs, **additional_kwargs)


@potto_app.command(name="run-server")
def run_uvicorn_server(
    *,
    settings: Annotated[PottoSettings, cyclopts.Parameter(parse=False)],
):
    potto_app.console.print(BANNER)
    table = Table(title="Potto configuration")
    table.add_column("Parameter")
    table.add_column("Value")
    for k, v in settings.model_dump().items():
        if k == "uvicorn_num_workers" and settings.debug:
            v = "1 (reload mode)"
        table.add_row(k, str(v))
    potto_app.console.print(table)

    # NOTE: passing `app` as a string in order to enable uvicorn's reloading
    # feature, as per:
    #
    # https://github.com/Kludex/uvicorn/discussions/2553#discussion-7774794
    #

    uvicorn_args = [
        "uvicorn",
        "potto.webapp.main:create_app",
        f"--port={settings.bind_port}",
        f"--host={settings.bind_host}",
        "--factory",
        "--access-log",
    ]
    if settings.debug:
        uvicorn_args.extend(
            [
                "--reload",
                f"--reload-dir={str(Path(__file__).parents[1])}",
                "--reload-include=*.html",
                "--log-level=debug",
            ]
        )
    else:
        uvicorn_args.extend(
            [
                f"--workers={settings.uvicorn_num_workers}",
                "--log-level=info",
            ]
        )

    if (log_config_file := settings.uvicorn_log_config_file) is not None:
        uvicorn_args.append(f"--log-config={str(log_config_file)}")
    if settings.public_url.startswith("https://"):
        uvicorn_args.extend(
            [
                "--forwarded-allow-ips=*",
                "--proxy-headers",
            ]
        )
    sys.stdout.flush()
    sys.stderr.flush()
    os.execvp("uvicorn", uvicorn_args)
