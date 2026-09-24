import socket
import warnings
from pathlib import Path
from typing import (
    Any,
    Literal,
)

import jinja2
import pydantic
import pydantic_settings
import zmqtt
from faststream.mqtt import MQTTBroker
from pygeoapi import __version__ as pygeoapi_version
from starlette_babel import get_translator
from starlette_babel.contrib.jinja import configure_jinja_env

from . import jinjafilters
from .authn.oidc import OIDCProvider
from .authz.authorizer import PottoAuthorizer
from .authz.backend import LocalAuthorizationBackend
from .authz.protocols import AuthorizationBackendProtocol
from .authz.opa import OPAAuthorizationBackend
from .managers.collections import (
    CollectionManagerProtocol,
    CollectionManagerFactoryProtocol,
)
from .managers.processes import (
    ProcessManagerProtocol,
    ProcessManagerFactoryProtocol,
)
from .managers.servermetadata import (
    ServerMetadataProtocol,
    ServerMetadataManagerFactoryProtocol,
)
from .managers.useraccounts import (
    UserAccountProtocol,
    UserAccountManagerFactoryProtocol,
)
from .managers.postgis.config import PostgisManagerConfiguration
from .managers.postgis.manager import get_postgis_manager

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


class CollectionManagerSettings(pydantic.BaseModel):
    manager_factory: pydantic.ImportString[CollectionManagerFactoryProtocol] = (
        get_postgis_manager
    )
    settings_model: dict[str, Any] = pydantic.Field(
        default_factory=lambda: PostgisManagerConfiguration().model_dump()
    )


class ServerMetadataManagerSettings(pydantic.BaseModel):
    manager_factory: pydantic.ImportString[ServerMetadataManagerFactoryProtocol] = (
        get_postgis_manager
    )
    settings_model: dict[str, Any] = pydantic.Field(
        default_factory=lambda: PostgisManagerConfiguration().model_dump()
    )


class UserAccountManagerSettings(pydantic.BaseModel):
    manager_factory: pydantic.ImportString[UserAccountManagerFactoryProtocol] = (
        get_postgis_manager
    )
    settings_model: dict[str, Any] = pydantic.Field(
        default_factory=lambda: PostgisManagerConfiguration().model_dump()
    )


class ProcessManagerSettings(pydantic.BaseModel):
    manager_factory: pydantic.ImportString[ProcessManagerFactoryProtocol] = (
        get_postgis_manager
    )
    settings_model: dict[str, Any] = pydantic.Field(
        default_factory=lambda: PostgisManagerConfiguration().model_dump()
    )


class InternalMqttBrokerSettings(pydantic.BaseModel):
    url: pydantic.AnyUrl = pydantic.AnyUrl("mqtt://localhost:1883")


class ExternalMqttBrokerSettings(pydantic.BaseModel):
    url: pydantic.AnyUrl = pydantic.AnyUrl("mqtt://localhost:1884")


class PottoSettings(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="potto__",
        env_nested_delimiter="__",
        secrets_dir="/run/secrets",
    )

    bind_host: str = "127.0.0.1"
    bind_port: int = 3001
    debug: bool = False
    public_url: str = "http://localhost:3001"
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
    internal_mqtt_broker: InternalMqttBrokerSettings = InternalMqttBrokerSettings()
    external_mqtt_broker: ExternalMqttBrokerSettings = ExternalMqttBrokerSettings()

    # these use default_factory in order to defer construction until PottoSettings() is actually called,
    # by which point the model_rebuild() calls below have resolved these settings models' forward
    # reference to "PottoSettings" itself.
    collection_manager: CollectionManagerSettings = pydantic.Field(
        default_factory=lambda: CollectionManagerSettings()
    )
    server_metadata_manager: ServerMetadataManagerSettings = pydantic.Field(
        default_factory=lambda: ServerMetadataManagerSettings()
    )
    user_account_manager: UserAccountManagerSettings = pydantic.Field(
        default_factory=lambda: UserAccountManagerSettings()
    )
    process_manager: ProcessManagerSettings = pydantic.Field(
        default_factory=lambda: ProcessManagerSettings()
    )
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

    _internal_broker: MQTTBroker | None = None
    _collection_manager: CollectionManagerProtocol | None = None
    _server_metadata_manager: ServerMetadataProtocol | None = None
    _user_account_manager: UserAccountProtocol | None = None
    _process_manager: ProcessManagerProtocol | None = None
    _jinja_env: jinja2.Environment | None = None
    _oidc_provider: OIDCProvider | None = None
    _authorization_backend: AuthorizationBackendProtocol | None = None

    def get_jinja_env(self) -> jinja2.Environment:
        if self._jinja_env is None:
            self._jinja_env = _get_jinja_env(self)
        return self._jinja_env

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

    def get_authorizer(self) -> PottoAuthorizer:
        return PottoAuthorizer(self.get_authorization_backend())

    def get_internal_broker(self, role: Literal["api", "worker"]) -> MQTTBroker:
        if self._internal_broker is None:
            self._internal_broker = MQTTBroker(
                self.internal_mqtt_broker.url.unicode_string(),
                version="5.0",
                client_id=f"potto-{role}-{socket.gethostname()}",
                clean_session=True if role == "api" else False,
                # Retry forever with exponential backoff instead of giving up after
                # zmqtt's default of 5 attempts - the api role connects in a
                # non-blocking background task (see webapp/main.py's lifespan) and
                # must keep trying even if mosquitto is unreachable for a while.
                reconnect=zmqtt.ReconnectConfig(max_attempts=None),
            )

        return self._internal_broker

    def get_collection_manager(self) -> CollectionManagerProtocol:
        if self._collection_manager is None:
            self._collection_manager = self.collection_manager.manager_factory(
                self.collection_manager.settings_model, self
            )
        return self._collection_manager

    def get_server_metadata_manager(self) -> ServerMetadataProtocol:
        if self._server_metadata_manager is None:
            self._server_metadata_manager = (
                self.server_metadata_manager.manager_factory(
                    self.server_metadata_manager.settings_model, self
                )
            )
        return self._server_metadata_manager

    def get_user_account_manager(self) -> UserAccountProtocol:
        if self._user_account_manager is None:
            self._user_account_manager = self.user_account_manager.manager_factory(
                self.user_account_manager.settings_model, self
            )
        return self._user_account_manager

    def get_process_manager(self) -> ProcessManagerProtocol:
        if self._process_manager is None:
            self._process_manager = self.process_manager.manager_factory(
                self.process_manager.settings_model, self
            )
        return self._process_manager


# These each have a manager_factory field typed against a Callable whose signature
# references "PottoSettings" as a forward reference (to avoid a circular imports.
# Pydantic can't resolve that forward reference until
# PottoSettings itself is fully defined, so these models are rebuilt here.
CollectionManagerSettings.model_rebuild()
ServerMetadataManagerSettings.model_rebuild()
UserAccountManagerSettings.model_rebuild()
ProcessManagerSettings.model_rebuild()


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
