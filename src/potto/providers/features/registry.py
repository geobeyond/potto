from collections.abc import (
    Awaitable,
    Callable,
)
import json
import logging
from typing import (
    Any,
    TypeAlias,
    TYPE_CHECKING,
)

from sqlmodel.ext.asyncio.session import AsyncSession

from ...schemas.base import ProvidedDataType
from ...util import interpolate_configuration_value
from .._registry import ProviderRegistry
from .protocol import FeatureProviderProtocol

if TYPE_CHECKING:
    from ...schemas.potto import Collection
    from ...config import PottoSettings

logger = logging.getLogger(__name__)

SyncFeatureProviderFactory: TypeAlias = Callable[
    ["Collection", dict[str, Any], AsyncSession, "PottoSettings"],
    FeatureProviderProtocol,
]

AsyncFeatureProviderFactory: TypeAlias = Callable[
    ["Collection", dict[str, Any], AsyncSession, "PottoSettings"],
    Awaitable[FeatureProviderProtocol],
]

FeatureProviderFactory: TypeAlias = (
    SyncFeatureProviderFactory | AsyncFeatureProviderFactory
)

_registry: ProviderRegistry[
    ["Collection", dict[str, Any], AsyncSession, "PottoSettings"],
    FeatureProviderProtocol,
] = ProviderRegistry()


def register_feature_provider(name: str, factory: FeatureProviderFactory) -> None:
    _registry.register(name, factory)


async def get_feature_provider(
    collection: "Collection",
    session: AsyncSession,
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
    return await factory(collection, raw_provider_configuration, session, potto_config)
