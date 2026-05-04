from typing import (
    Annotated,
    Iterator,
)

import babel
from fastapi import (
    Depends,
    Path,
    Query,
    Request,
)
from fastapi.security import OAuth2PasswordBearer

from ... import config
from ...authz.base import AuthorizationBackendProtocol
from ...schemas.auth import PottoUser
from ...wrapper import Potto

# Local-auth default. In OIDC mode, get_current_user is replaced via
# dependency_overrides in create_api_app_from_settings so that both the
# runtime path and the OpenAPI security scheme are correct.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)


def get_settings() -> Iterator[config.PottoSettings]:
    yield config.get_settings()


def get_potto(
    settings: Annotated[config.PottoSettings, Depends(get_settings)],
) -> Iterator[Potto]:
    yield Potto(settings)


async def get_current_user(
    request: Request,
    _token: Annotated[str | None, Depends(oauth2_scheme)],
) -> PottoUser | None:
    return request.user if isinstance(request.user, PottoUser) else None


def get_current_locale(request: Request) -> babel.Locale:
    return babel.Locale.parse(request.state.language)


def get_authorization_backend(
    settings: Annotated[config.PottoSettings, Depends(get_settings)],
) -> AuthorizationBackendProtocol:
    return settings.get_authorization_backend()


def get_pagination_limit(
    settings: Annotated[config.PottoSettings, Depends(get_settings)],
    limit: Annotated[
        int | None,
        Query(gte=1, description="Maximum number of items to return per page."),
    ] = None,
) -> int:
    return min(limit or settings.page_size, settings.page_size_max)


SettingsDependency = Annotated[config.PottoSettings, Depends(get_settings)]
PottoDependency = Annotated[Potto, Depends(get_potto)]
UserDependency = Annotated[PottoUser | None, Depends(get_current_user)]
LocaleDependency = Annotated[babel.Locale, Depends(get_current_locale)]
AuthorizationBackendDependency = Annotated[
    AuthorizationBackendProtocol, Depends(get_authorization_backend)
]
PaginationLimitDependency = Annotated[int, Depends(get_pagination_limit)]
CollectionIdPath = Annotated[
    str, Path(description="Unique identifier of the collection.")
]
ItemIdPath = Annotated[str, Path(description="Unique identifier of the item.")]
UserIdPath = Annotated[str, Path(description="Unique identifier of the user.")]
