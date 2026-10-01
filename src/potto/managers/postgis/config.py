import json
from typing import (
    Annotated,
    Any,
)

import pydantic
import sqlmodel
from pydantic.networks import PostgresDsn
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio.engine import (
    AsyncEngine,
    create_async_engine,
)
from sqlalchemy.ext.asyncio.session import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from .oci import normalize_registry


def _parse_json_if_str(value: Any) -> Any:
    # settings_model is a plain dict, so values that come from environment
    # variables or secret files are not parsed into structured data beforehand
    return json.loads(value) if isinstance(value, str) else value


class OciRegistryCredential(pydantic.BaseModel):
    registry: Annotated[str, pydantic.AfterValidator(normalize_registry)]
    username: str
    password: pydantic.SecretStr


class OciDeploymentSettings(pydantic.BaseModel):
    """Settings for deploying processes whose execution unit is an OCI image."""

    # None means using docker's own defaults, which honour DOCKER_HOST. This also
    # works with other engines that offer a Docker-compatible API, such as podman
    docker_base_url: str | None = None
    docker_timeout_seconds: int = 600
    # None means any registry is allowed, an empty list means none is
    allowed_registries: (
        list[Annotated[str, pydantic.AfterValidator(normalize_registry)]] | None
    ) = None
    # registries not listed here use the engine's own credentials configuration
    registry_credentials: Annotated[
        list[OciRegistryCredential], pydantic.BeforeValidator(_parse_json_if_str)
    ] = pydantic.Field(default_factory=list)

    @pydantic.field_validator("allowed_registries", mode="before")
    @classmethod
    def _parse_allowed_registries(cls, value: Any) -> Any:
        return _parse_json_if_str(value)


class PostgisManagerConfiguration(pydantic.BaseModel):
    _db_engine: AsyncEngine | None = None
    _sync_db_engine: Engine | None = None
    _db_session_maker: async_sessionmaker | None = None

    # Configured independently per manager instance (collections/server-metadata/
    # user-accounts each have their own settings_model) - this manager owns its DB
    # connection outright, it does not inherit from PottoSettings.
    database_dsn: PostgresDsn = PostgresDsn(
        "postgresql+psycopg://potto:pottopass@localhost/potto"
    )

    # Only ever read directly by the test suite (tests/conftest.py, tests/live_server.py)
    # to override this manager's own database_dsn when running tests - not used by any
    # production code path.
    test_database_dsn: PostgresDsn = PostgresDsn(
        "postgresql+psycopg://potto:pottopass@localhost/potto_test"
    )

    oci: OciDeploymentSettings = pydantic.Field(default_factory=OciDeploymentSettings)

    def get_db_engine(self) -> AsyncEngine:
        if self._db_engine is None:
            self._db_engine = create_async_engine(self.database_dsn.unicode_string())
        return self._db_engine

    def get_sync_db_engine(self) -> Engine:
        if self._sync_db_engine is None:
            self._sync_db_engine = sqlmodel.create_engine(
                self.database_dsn.unicode_string()
            )
        return self._sync_db_engine

    def get_db_session_maker(self) -> async_sessionmaker:
        if self._db_session_maker is None:
            self._db_session_maker = async_sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.get_db_engine(),
                expire_on_commit=False,
                class_=AsyncSession,
            )
        return self._db_session_maker
