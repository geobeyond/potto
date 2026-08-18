import asyncio
import inspect
import json
import logging
import sys
from typing import (
    Annotated,
    Literal,
)

import cyclopts
from cyclopts.types import StdioPath
from ogcapi_registry.client import AsyncOpenAPIClient
from ogcapi_registry import (
    parse_conformance_classes,
    validate_ogc_api,
)
from rich.console import Group
from rich.padding import Padding
from rich.table import Table

from ..config import (
    get_settings,
    PottoSettings,
)
from ..webapp.main import create_api_app_from_settings


app = cyclopts.App(help_format="rich")
logger = logging.getLogger(__name__)


@app.meta.default
def launcher(
    *tokens: Annotated[str, cyclopts.Parameter(show=False, allow_leading_hyphen=True)],
):
    """Functionalities for performing validation of OpenAPI specifications"""
    command, bound, ignored = app.parse_args(tokens)
    additional_kwargs = {}
    if "settings" in ignored:
        additional_kwargs["settings"] = get_settings()

    if inspect.iscoroutinefunction(command):
        if bound is None:
            return asyncio.run(command(**additional_kwargs))
        else:
            return asyncio.run(
                command(*bound.args, **bound.kwargs, **additional_kwargs)
            )
    else:
        return command(*bound.args, **bound.kwargs, **additional_kwargs)


@app.command(name="export")
def export_openapi_document(
    output: Annotated[
        StdioPath,
        cyclopts.Parameter(
            help=(
                "Path to the openapi document that will be created. "
                "A value of '-' means write to stdout."
            )
        ),
    ] = StdioPath("-"),
    indent: bool = True,
    *,
    settings: Annotated[PottoSettings, cyclopts.Parameter(parse=False)],
):
    """Export the OpenAPI document.

    This is mainly useful for using the openapi document with third-party
    tools, usually for checking compliance - it is not required to run
    potto.
    """
    app = create_api_app_from_settings(settings)
    openapi_document = app.openapi()
    output.write_text(json.dumps(openapi_document, indent=2 if indent else None))


@app.command(name="validate")
async def validate_openapi_spec(
    potto_api_base_url: str | None = None,
    format: Literal["json", "table"] = "table",
    error_on_failure: bool = True,
    *,
    settings: Annotated[PottoSettings, cyclopts.Parameter(parse=False)],
) -> None:
    """
    Validate a potto instance's OpenAPI document.

    Validates a potto instance's OpenAPI document against its own advertised
    conformance classes.

    Parameters
    ----------
    potto_api_base_url: str
        The base URL of the potto instance to validate. If not provided, the
        public URL from the settings will be used.
    format: str
        The output format for the validation results.
    error_on_failure: bool
        If True, the command will exit with a non-zero status code if validation fails.
    """
    base_url = potto_api_base_url or f"{settings.public_url}/api"
    client = AsyncOpenAPIClient(timeout=30)
    openapi_document, _ = await client.fetch(f"{base_url}/openapi.json")
    conformance_response, _ = await client.fetch(f"{base_url}/conformance")
    conformance_classes = parse_conformance_classes(conformance_response)
    validation_result = validate_ogc_api(openapi_document, conformance_classes)
    if format == "json":
        app.console.print(validation_result.model_dump_json(indent=2))
    else:
        if validation_result.is_valid:
            app.console.print("✅ Document is valid!")
        else:
            errors_table = Table("type", "details", title="Errors")
            for error in validation_result.errors:
                err = dict(error)
                type_ = err.pop("type", "Unknown")
                message = "\n".join(f"{k}: {v}" for k, v in err.items())
                errors_table.add_row(type_, message)
            app.console.print(
                Group(
                    Padding("[red]❌ Validation failed[/red]", 1),
                    errors_table,
                )
            )

        if len(validation_result.warnings) > 0:
            warnings_table = Table("message", title="Warnings")
            for warning in validation_result.warnings:
                warnings_table.add_row(
                    "\n".join(f"{k}: {v}" for k, v in warning.items())
                )
    if error_on_failure and not validation_result.is_valid:
        sys.exit(1)
