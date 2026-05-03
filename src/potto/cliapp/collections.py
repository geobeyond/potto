import asyncio
import inspect
import logging
import sys
from math import ceil
from pathlib import Path
from typing import (
    Annotated,
    Literal,
)

import cyclopts
import yaml
from cyclopts.types import NonNegativeInt
from rich.table import Table

from ..config import (
    get_settings,
    PottoSettings,
)
from ..db.queries import collections as collection_queries
from ..exceptions import PottoException
from ..operations import (
    auth as auth_ops,
    collections as collection_ops,
)
from ..schemas import cli as cli_schemas
from ..schemas.auth import (
    PottoScope,
    PottoUser,
)


collections_app = cyclopts.App()
logger = logging.getLogger(__name__)


@collections_app.meta.default
def launcher(
    *tokens: Annotated[str, cyclopts.Parameter(show=False, allow_leading_hyphen=True)],
):
    """Collection-related functionality."""
    command, bound, ignored = collections_app.parse_args(tokens)
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


@collections_app.command(name="import-from-pygeoapi")
async def import_collections_from_pygeoapi(
    pygeoapi_configuration: Path,
    resource: list[str] | None = None,
    overwrite: bool = False,
    *,
    settings: Annotated[PottoSettings, cyclopts.Parameter(parse=False)],
) -> None:
    """Import collections from pygeoapi."""
    if not pygeoapi_configuration.is_file():
        collections_app.error_console.print(
            "Error: pygeoapi configuration file not found."
        )
        sys.exit(1)

    raw_config = await asyncio.to_thread(Path(pygeoapi_configuration).read_text)
    pygeoapi_config = await asyncio.to_thread(yaml.safe_load, raw_config)

    num_imported = 0
    async with settings.get_db_session_maker()() as session:
        existing_admins, total_admins = await auth_ops.paginated_list_users(
            session, include_total=True, admin_filter=True
        )
        if not total_admins:
            collections_app.error_console.print(
                "Cannot import collections without there being at least one user with 'admin' "
                "scope to inherit them."
            )
            sys.exit(1)
        collection_owner = existing_admins[0].to_potto()
        existing_collections = await collection_queries.collect_all_user_collections(
            session
        )
        relevant_collections = {
            id_: res
            for id_, res in pygeoapi_config.get("resources", {}).items()
            if res.get("type") == "collection"
            and (resource is None or id_ in resource)
            and (
                overwrite
                or id_ not in [c.resource_identifier for c in existing_collections]
            )
        }
        for idx, (identifier, relevant_collection) in enumerate(
            relevant_collections.items()
        ):
            logger.debug(
                f"[{idx + 1}/{len(relevant_collections)}]Processing "
                f"collection {identifier!r}..."
            )
            try:
                await collection_ops.import_pygeoapi_collection(
                    session,
                    collection_owner,
                    settings.get_authorization_backend(),
                    identifier,
                    relevant_collection,
                    overwrite=overwrite,
                )
                num_imported += 1
            except PottoException as err:
                collections_app.error_console.print(
                    f"Could not import collection {identifier!r} - {err}"
                )
    collections_app.console.print(
        f"Done! Imported [{num_imported}/{len(relevant_collections)}] collections"
    )


@collections_app.command(name="list")
async def list_collections(
    page: NonNegativeInt = 1,
    page_size: NonNegativeInt = 20,
    format: Literal["json", "table"] = "table",
    *,
    settings: Annotated[PottoSettings, cyclopts.Parameter(parse=False)],
) -> None:
    """List collections."""
    async with settings.get_db_session_maker()() as session:
        collections, total = await collection_queries.paginated_list_user_collections(
            session,
            page=page,
            page_size=page_size,
            include_total=True,
        )
    assert total is not None
    result = cli_schemas.ItemList[cli_schemas.CollectionListItem](
        items=[cli_schemas.CollectionListItem.from_db_item(i) for i in collections],
        meta=cli_schemas.ItemListMeta(
            page=page,
            page_size=len(collections),
            total_items=total,
            total_pages=ceil(total / page_size),
        ),
    )
    if format == "json":
        collections_app.console.print_json(result.model_dump_json(indent=2))
    else:
        collection_table = Table(
            title="Collections",
            caption=f"Showing {result.meta.page_size} of {result.meta.total_items} items",
        )
        for field_name in cli_schemas.CollectionListItem.model_fields.keys():
            collection_table.add_column(field_name)
        for item_collection in result.items:
            table_row = []
            for field_name in cli_schemas.CollectionListItem.model_fields.keys():
                table_row.append(str(getattr(item_collection, field_name)))
            collection_table.add_row(*table_row)
        serialized = collection_table
        collections_app.console.print(serialized)


@collections_app.command(name="detail")
async def get_collection(
    collection_identifier: str,
    format: Literal["json", "table"] = "table",
    *,
    settings: Annotated[PottoSettings, cyclopts.Parameter(parse=False)],
) -> None:
    """Get details about a collection."""
    user = PottoUser(
        id="cli", username="cli", is_active=True, scopes=[PottoScope.ADMIN.value]
    )
    async with settings.get_db_session_maker()() as session:
        if not (
            collection := await collection_ops.get_collection_by_resource_identifier(
                session,
                user,
                settings.get_authorization_backend(),
                collection_identifier,
            )
        ):
            raise SystemExit(f"Error: Collection {collection_identifier!r} not found.")
        editors = await collection_queries.get_collection_editors(
            session, collection.resource_identifier
        )
        viewers = await collection_queries.get_collection_viewers(
            session, collection.resource_identifier
        )
    result = cli_schemas.CollectionDetail.from_db_item(
        collection, editors=editors, viewers=viewers
    )
    if format == "json":
        collections_app.console.print_json(result.model_dump_json(indent=2))
    else:
        detail_table = Table(title="Collection Details")
        detail_table.add_column("property")
        detail_table.add_column("value")
        for field_name in cli_schemas.CollectionDetail.model_fields.keys():
            detail_table.add_row(field_name, str(getattr(result, field_name)))
        collections_app.console.print(detail_table)


@collections_app.command(name="delete")
async def delete_collections(
    *collection_identifier: str,
    settings: Annotated[PottoSettings, cyclopts.Parameter(parse=False)],
) -> None:
    """Delete collections."""
    user = PottoUser(
        id="cli", username="cli", is_active=True, scopes=[PottoScope.ADMIN.value]
    )
    found_error = False
    async with settings.get_db_session_maker()() as session:
        for id_ in collection_identifier:
            if not (
                db_collection
                := await collection_ops.get_collection_by_resource_identifier(
                    session, user, settings.get_authorization_backend(), id_
                )
            ):
                collections_app.error_console.print(f"Collection {id_!r} not found.")
                found_error = True
                continue
            assert db_collection.id is not None
            try:
                await collection_ops.delete_collection(
                    session,
                    user,
                    settings.get_authorization_backend(),
                    db_collection.id,
                )
                collections_app.console.print(f"Collection {id_!r} deleted")
            except PottoException as err:
                collections_app.error_console.print(
                    f"Could not delete {collection_identifier!r} - {err}"
                )
                found_error = True
                continue
    sys.exit(0 if not found_error else 1)


@collections_app.command(name="grant-access")
async def grant_collection_access(
    collection_identifier: str,
    user_id: str,
    role: Literal["editor", "viewer"],
    *,
    settings: Annotated[PottoSettings, cyclopts.Parameter(parse=False)],
) -> None:
    """Grant a user editor or viewer access to a collection."""
    user = PottoUser(
        id="cli", username="cli", is_active=True, scopes=[PottoScope.ADMIN.value]
    )
    async with settings.get_db_session_maker()() as session:
        collection = await collection_ops.get_collection_by_resource_identifier(
            session, user, settings.get_authorization_backend(), collection_identifier
        )
        if collection is None:
            raise SystemExit(f"Error: Collection {collection_identifier!r} not found.")
        try:
            await collection_ops.grant_collection_access(
                session,
                user,
                settings.get_authorization_backend(),
                user_id,
                collection,
                role,
            )
        except PottoException as err:
            raise SystemExit(f"Error: {err}")
    collections_app.console.print(
        f"Granted {role!r} access on {collection_identifier!r} to user {user_id!r}."
    )


@collections_app.command(name="revoke-access")
async def revoke_collection_access(
    collection_identifier: str,
    user_id: str,
    *,
    settings: Annotated[PottoSettings, cyclopts.Parameter(parse=False)],
) -> None:
    """Revoke a user's access to a collection."""
    user = PottoUser(
        id="cli", username="cli", is_active=True, scopes=[PottoScope.ADMIN.value]
    )
    async with settings.get_db_session_maker()() as session:
        collection = await collection_ops.get_collection_by_resource_identifier(
            session, user, settings.get_authorization_backend(), collection_identifier
        )
        if collection is None:
            raise SystemExit(f"Error: Collection {collection_identifier!r} not found.")
        try:
            await collection_ops.revoke_collection_access(
                session, user, settings.get_authorization_backend(), user_id, collection
            )
        except PottoException as err:
            raise SystemExit(f"Error: {err}")
    collections_app.console.print(
        f"Revoked access on {collection_identifier!r} from user {user_id!r}."
    )
