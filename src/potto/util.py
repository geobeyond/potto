import asyncio
import concurrent.futures
import logging
import os
import re
import typing
import uuid
from typing import (
    cast,
    Coroutine,
    TypeVar,
)

from .exceptions import PottoException
from .constants import CollectionType

logger = logging.getLogger(__name__)

if typing.TYPE_CHECKING:
    from .config import PottoSettings
    from .schemas.collections import Collection

_T = TypeVar("_T")


def run_sync(coro: Coroutine[typing.Any, typing.Any, _T]) -> _T:
    """Run an awaitable from synchronous code, regardless of the caller's async context.

    A plain ``asyncio.run()`` fails when called from within a running event loop
    (e.g. uvicorn calling a sync app factory from its own loop). Running in a new
    thread guarantees a fresh event loop regardless of the caller's context.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return cast(_T, pool.submit(asyncio.run, coro).result())


def get_collection_type(pygeoapi_collection: dict) -> CollectionType:
    provider_types = set(
        [p.get("type") for p in pygeoapi_collection.get("providers", [])]
    )
    collection_type_mapping = {
        "feature": CollectionType.FEATURE_COLLECTION,
        "record": CollectionType.RECORD_COLLECTION,
        "coverage": CollectionType.COVERAGE,
        # mapping provider 'map' to 'CollectionType.COVERAGE' is really an arbitrary mapping,
        # pygeoapi does not seem to know about the underlying type of data of a map
        "map": CollectionType.COVERAGE,
    }
    try:
        return collection_type_mapping[
            provider_types.intersection(set(collection_type_mapping)).pop()
        ]
    except (TypeError, KeyError) as err:
        raise PottoException(f"Unsupported collection type: {provider_types=}") from err


# TODO: check this function's usage of settings
def get_collection_pagination_limit(
    request_limit: int | None, collection: "Collection", settings: "PottoSettings"
) -> int:
    requested_limit = request_limit or (
        collection.custom_page_size or settings.page_size
    )
    return min(
        requested_limit, collection.custom_page_size_max or settings.page_size_max
    )


def interpolate_configuration_value(value: str, env_whitelist: list[str]) -> str:

    def make_replacement(re_match: re.Match) -> str:
        default_value = "UNAUTHORIZED_ENVIRONMENT_ACCESS"
        env_variable_name = re_match.group(1)
        env_variable_value = default_value
        if (
            env_variable_name.startswith("POTTO__")
            or env_variable_name in env_whitelist
        ):
            env_variable_value = os.getenv(str(env_variable_name), "ENV_VAR_NOT_FOUND")
        return env_variable_value

    return re.sub(r"\${?(\w+)}?", make_replacement, value)


def create_correlation_id() -> str:
    return str(uuid.uuid4())
