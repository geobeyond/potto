from collections.abc import (
    Awaitable,
    Callable,
)
import json
import logging
from typing import (
    Any,
    cast,
    TypeAlias,
    TYPE_CHECKING,
)

from sqlalchemy.ext.asyncio import AsyncSession

from ...schemas.base import (
    ProvidedDataType,
    ProviderType,
    PottoProvider,
)
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
):
    if collection.providers is None:
        return None
    try:
        potto_provider = collection.providers[ProvidedDataType.FEATURE]
    except KeyError:
        return None
    if potto_provider.provider_type != ProviderType.POTTO:
        raise ValueError("Only potto providers are supported")
    potto_provider = cast(PottoProvider, potto_provider)
    details = potto_provider.details
    if details.provider_name is None:
        raise ValueError("provider_name is required")
    if (factory := _registry.get(details.provider_name)) is None:
        raise ValueError(f"Unknown provider: {details.provider_name}")

    raw_provider_configuration = json.loads(
        interpolate_configuration_value(
            json.dumps(details.config), potto_config.env_whitelist
        )
    )
    logger.debug(f"{details.config=}")
    logger.debug(f"{raw_provider_configuration=}")
    return await factory(collection, raw_provider_configuration, session, potto_config)
