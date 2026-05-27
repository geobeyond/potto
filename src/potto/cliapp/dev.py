import asyncio
import inspect
import logging
import sys
from anyio import Path
from typing import (
    Annotated,
    Literal,
)

import cyclopts
from rich.table import Table

from .. import exceptions as potto_exceptions
from ..config import (
    get_settings,
    PottoSettings,
)
from ..operations import (
    auth as auth_ops,
    collections as collection_ops,
)
from ..schemas.collections import CollectionCreate
from ..schemas.base import (
    CollectionType,
    ProvidedDataType,
    PottoProvider,
)
from ..schemas.cli import CollectionDetail

dev_app = cyclopts.App(help_format="rich")
logger = logging.getLogger(__name__)


@dev_app.meta.default
def launcher(
    *tokens: Annotated[str, cyclopts.Parameter(show=False, allow_leading_hyphen=True)],
):
    """Functionalities for facilitating the development of potto"""
    command, bound, ignored = dev_app.parse_args(tokens)
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


@dev_app.command(name="feature-collection-from-file")
async def generate_feature_collection_from_file(
    dataset_file: Path,
    *,
    identifier: str | None = None,
    is_public: bool = False,
    gdal_open_options_driver_name: str | None = None,
    format: Literal["json", "table"] = "table",
    settings: Annotated[PottoSettings, cyclopts.Parameter(parse=False)],
):
    """Creates a potto feature collection from an input file."""
    if not await dataset_file.exists():
        dev_app.error_console.print("[red]Error:[/red] dataset file does not exist.")
        sys.exit(1)
    async with settings.get_db_session_maker()() as session:
        existing_admins, total_admins = await auth_ops.paginated_list_users(
            session, include_total=True, admin_filter=True
        )
        if not total_admins:
            dev_app.error_console.print(
                "Cannot import collections without there being at least one user with 'admin' "
                "scope to inherit them."
            )
            sys.exit(1)
        collection_owner = existing_admins[0].to_potto()
        provider_conf: dict[str, str | dict[str, str]] = {
            "data_source_uri": str(await dataset_file.absolute()),
        }
        if gdal_open_options_driver_name:
            provider_conf["gdal_open_options"] = {
                "driver_name": gdal_open_options_driver_name,
            }
        to_create = CollectionCreate(
            resource_identifier=identifier or dataset_file.stem,
            owner_id=collection_owner.id,
            is_public=is_public,
            collection_type=CollectionType.FEATURE_COLLECTION,
            title=(identifier or dataset_file.stem).title(),
            providers={
                ProvidedDataType.FEATURE.value: PottoProvider(
                    provider_name="pyogrio", config=provider_conf
                ),
            },
        )
        try:
            created = await collection_ops.create_collection(
                session,
                collection_owner,
                settings.get_authorization_backend(),
                to_create,
                settings,
            )
        except potto_exceptions.PottoException as err:
            dev_app.console.print(f"[red]Error:[/red] {err}")
            sys.exit(1)
        result = CollectionDetail.from_db_item(created)
    if format == "json":
        dev_app.console.print_json(result.model_dump_json(indent=2))
    else:
        detail_table = Table(title="Collection Details")
        detail_table.add_column("property")
        detail_table.add_column("value")
        for field_name in CollectionDetail.model_fields.keys():
            detail_table.add_row(field_name, str(getattr(result, field_name)))
        dev_app.console.print(detail_table)
