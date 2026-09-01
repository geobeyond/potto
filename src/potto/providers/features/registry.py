from collections.abc import (
    Awaitable,
    Callable,
)
import hashlib
import json
import logging
from typing import (
    Any,
    TypeAlias,
    TYPE_CHECKING,
)

from ...constants import ProvidedDataType
from ...util import interpolate_configuration_value
from .._registry import ProviderRegistry
from .protocol import FeatureProviderProtocol

if TYPE_CHECKING:
    from ...schemas.collections import Collection
    from ...config import PottoSettings

logger = logging.getLogger(__name__)

SyncFeatureProviderFactory: TypeAlias = Callable[
    ["Collection", dict[str, Any], "PottoSettings"],
    FeatureProviderProtocol,
]

AsyncFeatureProviderFactory: TypeAlias = Callable[
    ["Collection", dict[str, Any], "PottoSettings"],
    Awaitable[FeatureProviderProtocol],
]

FeatureProviderFactory: TypeAlias = (
    SyncFeatureProviderFactory | AsyncFeatureProviderFactory
)

_registry: ProviderRegistry[
    ["Collection", dict[str, Any], "PottoSettings"],
    FeatureProviderProtocol,
] = ProviderRegistry()

# Insertion-ordered dict used as a bounded FIFO cache.
# Key: (collection_id, sha256[:16] of provider_name+config).
# Evicts the oldest entry when provider_cache_size is exceeded.
_provider_cache: dict[tuple[str, str], FeatureProviderProtocol] = {}


def register_feature_provider(name: str, factory: FeatureProviderFactory) -> None:
    _registry.register(name, factory)


def _cache_key(
    collection_id: str, provider_name: str, raw_config: dict[str, Any]
) -> tuple[str, str]:
    payload = json.dumps(
        {"provider": provider_name, "config": raw_config}, sort_keys=True
    )
    return (collection_id, hashlib.sha256(payload.encode()).hexdigest()[:16])


async def get_feature_provider(
    collection: "Collection",
    potto_config: "PottoSettings",
) -> FeatureProviderProtocol | None:
    if collection.providers is None:
        return None
    try:
        provider = collection.providers[ProvidedDataType.FEATURE]
    except KeyError:
        return None
    if (factory := _registry.get(provider.provider_name)) is None:
        raise ValueError(f"Unknown provider: {provider.provider_name}")
    raw_provider_configuration = json.loads(
        interpolate_configuration_value(
            json.dumps(provider.config), potto_config.env_whitelist
        )
    )
    logger.debug(f"{provider.config=}")
    logger.debug(f"{raw_provider_configuration=}")

    if potto_config.feature_provider_cache_size == 0:
        return await factory(collection, raw_provider_configuration, potto_config)

    key = _cache_key(
        collection.identifier, provider.provider_name, raw_provider_configuration
    )
    if key in _provider_cache:
        return _provider_cache[key]

    instance = await factory(collection, raw_provider_configuration, potto_config)

    if len(_provider_cache) >= potto_config.feature_provider_cache_size:
        del _provider_cache[next(iter(_provider_cache))]
    _provider_cache[key] = instance
    return instance
