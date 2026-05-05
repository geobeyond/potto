import asyncio
import inspect
import logging
from typing import Annotated

import cyclopts

from ..config import (
    get_settings,
    PottoSettings,
)
from ..db.queries.auth import paginated_list_users
from ..db.queries import collections as collection_queries
from ..operations import collections as collection_ops

from ..schemas import (
    base as base_schemas,
    collections as collection_schemas,
)

cite_app = cyclopts.App(help_format="rich")
logger = logging.getLogger(__name__)


@cite_app.meta.default
def launcher(
    *tokens: Annotated[str, cyclopts.Parameter(show=False, allow_leading_hyphen=True)],
):
    """Functionalities for facilitating CITE testing"""
    command, bound, ignored = cite_app.parse_args(tokens)
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


@cite_app.command(name="bootstrap-ogcapi-features-1")
async def bootstrap_for_cite_ogcapi_features(
    *,
    settings: Annotated[PottoSettings, cyclopts.Parameter(parse=False)],
) -> None:
    """
    Ensure DB is populated for running the official ogcapi-features-1.0 test suite.

    [red]WARNING:[/red] This command creates data on the main potto database!
    """

    async with settings.get_db_session_maker()() as session:
        (
            paginated_collections,
            _,
        ) = await collection_queries.paginated_list_public_collections(
            session,
            collection_type_filter=[base_schemas.CollectionType.FEATURE_COLLECTION],
        )
        if len(paginated_collections) > 0:
            cite_app.console.print(
                "DB already has public collections, no need to create more"
            )
            return None
        identifier = "obs-cite"
        if (
            await collection_queries.get_collection_by_resource_identifier(
                session, identifier
            )
        ) is not None:
            cite_app.error_console.print(
                f"[red]Error:[/red] a collection named {identifier!r} already "
                f"exists but is not public"
            )
            raise SystemExit(1)
        admin_users, _ = await paginated_list_users(
            session, admin_filter=True, include_total=False
        )
        if len(admin_users) == 0:
            cite_app.error_console.print(
                "[red]Error:[/red] Need at least one admin user to be available"
            )
            raise SystemExit(1)
        admin_user = admin_users[0]
        collection_to_create = collection_schemas.CollectionCreate(
            resource_identifier="obs-cite",
            owner_id=admin_user.id,
            is_public=True,
            collection_type=base_schemas.CollectionType.FEATURE_COLLECTION,
            title="Testing obs feature collection",
            spatial_extent="POLYGON ((-122 43, -122 49, -75 49, -75 43, -122 43))",
            spatial_extent_crs="http://www.opengis.net/def/crs/OGC/1.3/CRS84",
            providers={
                "feature": base_schemas.CollectionProvider(
                    python_callable="potto.pygeoapi_providers.PygeoapiConfigWktFeatureProvider",
                    config=base_schemas.CollectionProviderConfiguration(
                        options={},
                        data={
                            "features": [
                                {
                                    "id": 371,
                                    "geometry": "POINT (-75 45)",
                                    "properties": {
                                        "stn_id": 35,
                                        "datetime": "2001-10-30T14:24:55Z",
                                        "value": 89.9,
                                    },
                                },
                                {
                                    "id": 377,
                                    "geometry": "POINT (-75 45)",
                                    "properties": {
                                        "stn_id": 35,
                                        "datetime": "2002-10-30T18:31:38Z",
                                        "value": 93.9,
                                    },
                                },
                                {
                                    "id": 238,
                                    "geometry": "POINT (-79 43)",
                                    "properties": {
                                        "stn_id": 2147,
                                        "datetime": "2007-10-30T08:57:29Z",
                                        "value": 103.5,
                                    },
                                },
                                {
                                    "id": 297,
                                    "geometry": "POINT (-79 43)",
                                    "properties": {
                                        "stn_id": 2147,
                                        "datetime": "2003-10-30T07:37:29Z",
                                        "value": 93.5,
                                    },
                                },
                                {
                                    "id": 964,
                                    "geometry": "POINT (-122 49)",
                                    "properties": {
                                        "stn_id": 604,
                                        "datetime": "2000-10-30T18:24:39Z",
                                        "value": 99.9,
                                    },
                                },
                            ]
                        },
                    ),
                )
            },
        )
        await collection_ops.create_collection(
            session,
            admin_user.to_potto(),
            settings.get_authorization_backend(),
            collection_to_create,
        )
        cite_app.console.print(
            f"[green]:heavy_check_mark: Created collection {collection_to_create.resource_identifier}[/green]"
        )
        return None
