import warnings
from pathlib import Path

import jinja2
import pydantic
import pydantic_settings
import sqlmodel
from pydantic.networks import PostgresDsn
from pygeoapi import __version__ as pygeoapi_version
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio.session import async_sessionmaker
from sqlalchemy.ext.asyncio.engine import (
    AsyncEngine,
    create_async_engine,
)
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette_babel import get_translator
from starlette_babel.contrib.jinja import configure_jinja_env

from . import jinjafilters
from .authn.oidc import OIDCProvider
from .authz.base import AuthorizationBackendProtocol
from .authz.backend import LocalAuthorizationBackend
from .authz.opa import OPAAuthorizationBackend

warnings.filterwarnings(
    "ignore",
    message="directory .* does not exist",
    module="pydantic_settings",
)


class OPASettings(pydantic.BaseModel):
    url: str
    policy_path: str = "potto/authz"


class OIDCSettings(pydantic.BaseModel):
    issuer: str
    client_id: str
    client_secret: pydantic.SecretStr
    scopes: list[str] = ["openid", "email", "profile"]
    # Dot-notation claim path for roles to map to potto scopes, e.g. "realm_access.roles"
    roles_claim: str | None = None
    # Audience expected in access tokens; None skips audience verification
    access_token_audience: str | None = None


class PottoSettings(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="potto__",
        env_nested_delimiter="__",
        secrets_dir="/run/secrets",
    )

    bind_host: str = "127.0.0.1"
    bind_port: int = 3001
    retriever_collections: str = "potto.retrievers.retrieve_collections"
    retriever_server_metadata: str = "potto.retrievers.retrieve_server_metadata"
    database_dsn: PostgresDsn = PostgresDsn(
        "postgresql+psycopg://potto:pottopass@localhost/potto"
    )
    test_database_dsn: PostgresDsn = PostgresDsn(
        "postgresql+psycopg://potto:pottopass@localhost/potto_test"
    )
    debug: bool = False
    public_url: str = "http://localhost:3001"
    pygeoapi_config_file: Path = Path.home() / "pygeoapi-config.yml"
    env_whitelist: list[str] = pydantic.Field(default_factory=list)
    templates_dir: Path | None = None
    admin_templates_dir: Path | None = None
    translations_dir: Path | None = None
    languages: list[str] = ["en"]
    reload_dirs: str | list[str] | None = None
    session_secret_key: pydantic.SecretStr = pydantic.SecretStr("somesecretkey")
    static_dir: Path | None = None
    uvicorn_num_workers: int = 8
    uvicorn_log_config_file: Path | None = None
    local_data_root: Path = Path.home() / "potto_data"
    oidc: OIDCSettings | None = None
    opa: OPASettings | None = None
    page_size: int = 20
    page_size_max: int = 100
    use_oas30_fixes: bool = pydantic.Field(
        default=False,
        description=(
            "Apply OAS 3.0 compatibility fixes to the generated OpenAPI schema "
            "(converts Pydantic v2 anyOf+null to nullable:true). Required for OGC "
            "CITE validation, which only supports OAS 3.0."
        ),
    )
    feature_provider_cache_size: int = pydantic.Field(
        default=256,
        ge=0,
        description=(
            "Maximum number of feature provider instances to keep in the cache. "
            "Each entry holds an open connection (e.g. a DuckDB in-memory DB), so "
            "tune this against available memory. 256 is suitable for deployments with "
            "up to a few hundred collections under typical power-law access patterns. "
            "Set to 0 to disable caching (useful for testing)."
        ),
    )

    _jinja_env: jinja2.Environment | None = None
    _db_engine: AsyncEngine | None = None
    _sync_db_engine: Engine | None = None
    _db_session_maker: async_sessionmaker | None = None
    _oidc_provider: OIDCProvider | None = None
    _authorization_backend: AuthorizationBackendProtocol | None = None

    def get_jinja_env(self) -> jinja2.Environment:
        if self._jinja_env is None:
            self._jinja_env = _get_jinja_env(self)
        return self._jinja_env

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

    def get_oidc_provider(self) -> OIDCProvider | None:
        if self.oidc is None:
            return None
        if self._oidc_provider is None:
            self._oidc_provider = OIDCProvider(
                issuer=self.oidc.issuer,
                client_id=self.oidc.client_id,
                client_secret=self.oidc.client_secret.get_secret_value(),
                scopes=self.oidc.scopes,
                roles_claim=self.oidc.roles_claim,
                access_token_audience=self.oidc.access_token_audience,
            )
        return self._oidc_provider

    def get_authorization_backend(self) -> AuthorizationBackendProtocol:
        if self._authorization_backend is None:
            if self.opa is not None:
                self._authorization_backend = OPAAuthorizationBackend(
                    self.opa.url, self.opa.policy_path
                )
            else:
                self._authorization_backend = LocalAuthorizationBackend()
        return self._authorization_backend

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


def get_settings() -> PottoSettings:
    return PottoSettings()


def _get_jinja_env(settings: PottoSettings) -> jinja2.Environment:
    if settings.translations_dir:
        shared_translator = get_translator()
        shared_translator.load_from_directory(settings.translations_dir)
    template_loaders: list[jinja2.BaseLoader] = [
        jinja2.PackageLoader("potto.webapp", "templates"),
        jinja2.PackageLoader("pygeoapi", "templates"),
    ]
    if settings.templates_dir:
        template_loaders.insert(
            0,
            jinja2.FileSystemLoader(settings.templates_dir),
        )
    jinja_env = jinja2.Environment(
        loader=jinja2.ChoiceLoader(template_loaders),
        autoescape=True,
        extensions=[
            "jinja2.ext.i18n",
        ],
    )
    jinja_env.filters.update(
        {
            "get_translatable_string": jinjafilters.get_translatable_string,
            "to_json": jinjafilters.to_json,
            "format_datetime": jinjafilters.format_datetime,
            "format_duration": jinjafilters.format_duration,
            "human_size": jinjafilters.human_size,
            "get_path_basename": jinjafilters.get_path_basename,
            "get_breadcrumbs": jinjafilters.get_breadcrumbs,
            "filter_dict_by_key_value": jinjafilters.filter_dict_by_key_value,
        }
    )
    jinja_env.globals.update(  # ty: ignore[no-matching-overload]
        {
            "settings": settings,
            "pygeoapi_version": pygeoapi_version,
            "icons": jinjafilters.ICONS,
            "colors": jinjafilters.COLORS,
        }
    )
    configure_jinja_env(jinja_env)
    return jinja_env
