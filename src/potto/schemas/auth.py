import dataclasses
import enum
import re
import typing

import pydantic
from jinja2 import Template
from starlette.authentication import BaseUser
from starlette.requests import Request

_DYNAMIC_SCOPE_PATTERN = re.compile(r"^collection-.+:(editor|viewer)$")


class PottoScope(str, enum.Enum):
    ADMIN = "admin"
    SERVER_METADATA_EDITOR = "server-metadata:editor"
    COLLECTIONS_CREATOR = "collections:creator"

    @staticmethod
    def collection_editor(identifier: str) -> str:
        return f"collection-{identifier}:editor"

    @staticmethod
    def collection_viewer(identifier: str) -> str:
        return f"collection-{identifier}:viewer"


def _validate_scope(scope: str) -> str:
    fixed_values = {s.value for s in PottoScope}
    if scope in fixed_values:
        return scope
    if _DYNAMIC_SCOPE_PATTERN.match(scope):
        return scope
    raise ValueError(
        f"Invalid scope {scope!r}. Must be one of {sorted(fixed_values)} "
        f"or match pattern 'collection-<identifier>:(editor|viewer)'"
    )


class PottoUser(pydantic.BaseModel, BaseUser):
    id: str
    username: str
    email: str | None = None
    is_active: bool
    scopes: list[str] = []

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def display_name(self) -> str:
        return self.username

    @property
    def identity(self) -> str:
        return str(self.id)

    def __admin_repr__(self, request: Request) -> str:
        return self.username

    def __admin_select2_repr__(self, request: Request) -> str:
        return Template("<span>{{ name }}</span>", autoescape=True).render(
            name=self.username,
        )


ValidScope = typing.Annotated[str, pydantic.AfterValidator(_validate_scope)]


class BaseUserCreate(pydantic.BaseModel):
    username: str = pydantic.Field(min_length=5, max_length=20)
    is_active: bool = True
    scopes: list[ValidScope] = []
    email: str | None = None


class UserCreate(BaseUserCreate):
    password: pydantic.SecretStr = pydantic.Field(min_length=8)


class UserCreateFromOidc(BaseUserCreate):
    id: str


class UserUpdate(pydantic.BaseModel):
    password: str | None = pydantic.Field(default=None, min_length=8)
    email: str | None = None
    is_active: bool | None = None
    scopes: list[ValidScope] | None = None


@dataclasses.dataclass(frozen=True)
class UserFilter:
    username: str | None = None
    is_admin: bool | None = None


@dataclasses.dataclass(frozen=True)
class UserAccountManagerCapabilities:
    supports_creation: bool = False
    supports_modification: bool = False
    supports_deletion: bool = False
