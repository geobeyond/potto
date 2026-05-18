"""Potto item providers"""

from typing import (
    Any,
    Callable,
    Literal,
    Protocol,
)

import pydantic
from pydantic.json_schema import JsonSchemaValue
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models
from ..schemas.potto import Feature


# this should be in schemas (we have schemas.base.ItemFilter there)
class ItemFilter(pydantic.BaseModel):
    bbox: tuple[float, float, float, float] | None = None
    bbox_crs: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
    crs: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
    limit: int = pydantic.Field(default=10, ge=1, le=1000)
    offset: int = pydantic.Field(default=0, ge=0)
    properties: list[str] | None = None


class ItemProviderProtocol(Protocol):
    async def list_items(
        self,
        item_filter: ItemFilter | None = None,
    ) -> list[Feature]: ...

    async def count_items(
        self, item_filter: ItemFilter | None = None
    ) -> tuple[int, int]: ...

    async def get_item(
        self,
        item_id: str,
        crs: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
    ) -> Feature | None: ...

    async def get_schema(self) -> JsonSchemaValue: ...


class PyogrioItemProviderConfiguration(pydantic.BaseModel):
    provider_name: Literal["pyogrio"] = "pyogrio"


class PyogrioItemProvider:
    config: PyogrioItemProviderConfiguration

    def __init__(self, config: PyogrioItemProviderConfiguration):
        """An item provider that uses pyogrio to retrieve data."""
        self.config = config

    @classmethod
    def from_factory(
        cls, raw_config: dict[str, Any], session: AsyncSession
    ) -> "PyogrioItemProvider":
        config = PyogrioItemProviderConfiguration.model_validate(raw_config)
        return PyogrioItemProvider(config)

    async def list_items(self, item_filter: ItemFilter | None = None) -> list[Feature]:
        raise NotImplementedError

    async def count_items(
        self, item_filter: ItemFilter | None = None
    ) -> tuple[int, int]:
        raise NotImplementedError

    async def get_item(
        self,
        item_id: str,
        crs: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
    ) -> Feature | None:
        raise NotImplementedError

    async def get_schema(self) -> JsonSchemaValue:
        raise NotImplementedError


class PostgisItemProviderConfiguration(pydantic.BaseModel):
    provider_name: Literal["postgis"] = "postgis"


class PostgisItemProvider:
    config: PostgisItemProviderConfiguration
    db_session: AsyncSession

    def __init__(self, config: PostgisItemProviderConfiguration, session: AsyncSession):
        """An item provider that uses PostGIS to retrieve data."""
        self.config = config
        self.db_session = session

    @classmethod
    def from_factory(
        cls, raw_config: dict[str, Any], session: AsyncSession
    ) -> "PostgisItemProvider":
        config = PostgisItemProviderConfiguration.model_validate(raw_config)
        return PostgisItemProvider(config, session)

    async def list_items(self, item_filter: ItemFilter | None = None) -> list[Feature]:
        raise NotImplementedError

    async def count_items(
        self, item_filter: ItemFilter | None = None
    ) -> tuple[int, int]:
        raise NotImplementedError

    async def get_item(
        self,
        item_id: str,
        crs: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
    ) -> Feature | None:
        raise NotImplementedError

    async def get_schema(self) -> JsonSchemaValue:
        raise NotImplementedError


ItemProviderFactory = Callable[[dict[str, Any], AsyncSession], ItemProviderProtocol]

_ITEM_PROVIDER_REGISTRY: dict[str, ItemProviderFactory] = {}


def register_provider(name: str, factory: ItemProviderFactory) -> None:
    _ITEM_PROVIDER_REGISTRY[name] = factory


register_provider("pyogrio", PyogrioItemProvider.from_factory)
register_provider("postgis", PostgisItemProvider.from_factory)


async def get_provider(
    db_collection: models.Collection,
    session: AsyncSession,
) -> ItemProviderProtocol:
    """Provider factory."""
    raw_provider_config = db_collection.providers["feature"]  # ty: ignore[not-subscriptable]
    if (provider_name := raw_provider_config.get("provider_name")) is None:
        raise ValueError("provider_name is required")

    if (provider_factory := _ITEM_PROVIDER_REGISTRY.get(provider_name)) is None:
        raise ValueError(f"Unknown provider: {provider_name}")
    return provider_factory(raw_provider_config, session)
