"""Permission-checked business logic backing ``PostgisManager``.

The functions defined in this module always return instances of potto's public,
storage-agnostic schemas (``potto.schemas.*``), never this package's private ORM
models.
"""

import logging
import re
from typing import TYPE_CHECKING

import bcrypt
from sqlalchemy.exc import DatabaseError
from sqlmodel.ext.asyncio.session import AsyncSession

from ....authz.authorizer import (
    PottoAuthorizer,
    Principal,
    SystemPrincipal,
)
from .... import exceptions
from ....exceptions import (
    PottoCannotCreateUserException,
    PottoCannotDeleteUserException,
    PottoCannotEditUserException,
    PottoCannotSetAdminScopeException,
    PottoCannotSetScopesException,
    PottoCannotViewUserException,
    PottoNotFoundException,
)
from ....schemas.auth import (
    PottoScope,
    PottoUser,
    UserCreate,
    UserCreateFromOidc,
    UserUpdate,
)
from ..db.commands import auth as auth_commands
from ..db.queries import (
    auth as auth_queries,
    collections as collection_queries,
    processes as process_queries,
)

if TYPE_CHECKING:
    from ....schemas.collections import Collection
    from ....schemas.processes import Process

logger = logging.getLogger(__name__)

_EDITOR_SCOPE_RE = re.compile(r"^collection-(.+):editor$")


async def create_user(
    session: AsyncSession,
    requesting_user: Principal | None,
    authorizer: PottoAuthorizer,
    to_create: UserCreate,
) -> PottoUser:
    if not await authorizer.can_create_user(requesting_user):
        raise PottoCannotCreateUserException(
            "User does not have permission to create new users."
        )
    # can_create_user() above already rejects a None requesting_user.
    assert requesting_user is not None
    if to_create.scopes:
        await _check_scope_assignment(
            session, requesting_user, authorizer, to_create.scopes
        )
    created = await auth_commands.create_user(session, to_create)
    return created.to_potto()


async def update_user(
    session: AsyncSession,
    requesting_user: Principal | None,
    authorizer: PottoAuthorizer,
    user_id: str,
    to_update: UserUpdate,
) -> PottoUser:
    if not await authorizer.can_edit_user(requesting_user):
        raise PottoCannotEditUserException(
            "User does not have permission to edit user accounts."
        )
    # can_edit_user() above already rejects a None requesting_user.
    assert requesting_user is not None
    db_user = await auth_queries.get_user(session, user_id)
    if db_user is None:
        raise PottoNotFoundException(f"User {user_id!r} does not exist.")
    if to_update.scopes is not None:
        await _check_scope_assignment(
            session, requesting_user, authorizer, to_update.scopes
        )
    updated = await auth_commands.update_user(session, db_user, to_update)
    return updated.to_potto()


async def _check_scope_assignment(
    session: AsyncSession,
    requesting_user: Principal,
    authorizer: PottoAuthorizer,
    new_scopes: list[str],
) -> None:
    if PottoScope.ADMIN.value in new_scopes:
        if not await authorizer.can_assign_admin_scope(requesting_user):
            raise PottoCannotSetAdminScopeException(
                "User does not have permission to assign the admin scope."
            )
    match requesting_user:
        case SystemPrincipal():
            return
        case _:
            editable_identifiers = await _get_editable_collection_identifiers(
                session, requesting_user
            )
            if not await authorizer.can_set_user_scopes(
                requesting_user, new_scopes, editable_identifiers
            ):
                raise PottoCannotSetScopesException(
                    "User does not have permission to set these scopes."
                )


async def _get_editable_collection_identifiers(
    session: AsyncSession,
    user: PottoUser,
) -> list[str]:
    owned = await collection_queries.get_owned_collection_identifiers(session, user.id)
    from_scopes = [
        m.group(1) for scope in user.scopes if (m := _EDITOR_SCOPE_RE.match(scope))
    ]
    return list({*owned, *from_scopes})


async def delete_user(
    session: AsyncSession,
    requesting_user: Principal | None,
    authorizer: PottoAuthorizer,
    user_id: str,
) -> None:
    if not await authorizer.can_delete_user(requesting_user):
        raise PottoCannotDeleteUserException(
            "User does not have permission to delete user accounts."
        )
    return await auth_commands.delete_user(session, user_id)


async def paginated_list_users(
    session: AsyncSession,
    requesting_user: Principal | None,
    authorizer: PottoAuthorizer,
    *,
    username_filter: str | None = None,
    admin_filter: bool = False,
    page: int = 1,
    page_size: int = 20,
    include_total: bool = False,
) -> tuple[list[PottoUser], int | None]:
    if not await authorizer.can_view_user(requesting_user):
        raise PottoCannotViewUserException(
            "User does not have permission to view user accounts."
        )
    users, count = await auth_queries.paginated_list_users(
        session,
        page=page,
        page_size=page_size,
        include_total=include_total,
        username_filter=username_filter,
        admin_filter=admin_filter,
    )
    return [u.to_potto() for u in users], count


async def get_user(
    session: AsyncSession,
    requesting_user: Principal | None,
    authorizer: PottoAuthorizer,
    user_id: str,
) -> PottoUser | None:
    if not await authorizer.can_view_user(requesting_user):
        raise PottoCannotViewUserException(
            "User does not have permission to view user accounts."
        )
    db_user = await auth_queries.get_user(session, user_id)
    return db_user.to_potto() if db_user is not None else None


async def get_user_by_username(
    session: AsyncSession,
    requesting_user: Principal | None,
    authorizer: PottoAuthorizer,
    username: str,
) -> PottoUser | None:
    if not await authorizer.can_view_user(requesting_user):
        raise PottoCannotViewUserException(
            "User does not have permission to view user accounts."
        )
    db_user = await auth_queries.get_user_by_username(session, username)
    return db_user.to_potto() if db_user is not None else None


async def provision_oidc_user(
    session: AsyncSession,
    to_create: UserCreateFromOidc,
) -> PottoUser:
    created = await auth_commands.provision_oidc_user(session, to_create)
    return created.to_potto()


async def authenticate(
    session: AsyncSession,
    username: str,
    password: str,
) -> PottoUser | None:
    """Verify a local username/password pair, returning None on any failure."""
    db_user = await auth_queries.get_user_by_username(session, username)
    if db_user is None:
        logger.debug(f"Login failed: user {username!r} not found")
        return None
    if not db_user.is_active:
        logger.warning(f"Login failed: user {username!r} is inactive")
        return None
    if db_user.hashed_password is None:
        logger.warning(f"Login failed: user {username!r} has no local password")
        return None
    if not bcrypt.checkpw(password.encode(), db_user.hashed_password.encode()):
        logger.debug(f"Login failed: wrong password for user {username!r}")
        return None
    return db_user.to_potto()


async def list_resource_editors(
    session: AsyncSession,
    requesting_user: Principal | None,
    authorizer: PottoAuthorizer,
    resource_type: str,
    resource_identifier: str,
) -> list[PottoUser]:
    if not await authorizer.can_view_user(requesting_user):
        raise PottoCannotViewUserException(
            "User does not have permission to view resource editors."
        )
    if resource_type == "collection":
        editors = await collection_queries.get_collection_editors(
            session, resource_identifier
        )
    elif resource_type == "process":
        editors = await process_queries.get_process_editors(
            session, resource_identifier
        )
    else:
        raise NotImplementedError(
            f"Resource type {resource_type!r} is not supported yet."
        )
    return [e.to_potto() for e in editors]


async def list_resource_viewers(
    session: AsyncSession,
    requesting_user: Principal | None,
    authorizer: PottoAuthorizer,
    resource_type: str,
    resource_identifier: str,
) -> list[PottoUser]:
    if not await authorizer.can_view_user(requesting_user):
        raise PottoCannotViewUserException(
            "User does not have permission to view resource viewers."
        )
    if resource_type == "collection":
        viewers = await collection_queries.get_collection_viewers(
            session, resource_identifier
        )
    elif resource_type == "process":
        viewers = await process_queries.get_process_viewers(
            session, resource_identifier
        )
    else:
        raise NotImplementedError(
            f"Resource type {resource_type!r} is not supported yet."
        )
    return [v.to_potto() for v in viewers]


async def grant_collection_access(
    session: AsyncSession,
    granting_user: Principal,
    authorizer: PottoAuthorizer,
    target_user_id: str,
    collection: "Collection",
    role: str,
) -> None:
    if not await authorizer.can_edit_collection(granting_user, collection):
        raise exceptions.CannotModifyResourceAccess(
            "User does not have permission to grant access to this collection."
        )
    target_user = await auth_queries.get_user(session, target_user_id)
    if target_user is None:
        raise exceptions.UserNotFoundException(
            f"User with id {target_user_id!r} does not exist."
        )
    editor_scope = PottoScope.collection_editor(collection.identifier)
    viewer_scope = PottoScope.collection_viewer(collection.identifier)
    new_scopes = [
        s for s in target_user.scopes if s not in (editor_scope, viewer_scope)
    ]
    if role == "editor":
        new_scopes.append(editor_scope)
    else:
        new_scopes.append(viewer_scope)
    try:
        await auth_commands.update_user(
            session, target_user, UserUpdate(scopes=new_scopes)
        )
    except DatabaseError as err:
        raise exceptions.CannotModifyResourceAccess(str(err)) from err


async def revoke_collection_access(
    session: AsyncSession,
    revoking_user: Principal,
    authorizer: PottoAuthorizer,
    target_user_id: str,
    collection: "Collection",
) -> None:
    if not await authorizer.can_edit_collection(revoking_user, collection):
        raise exceptions.CannotModifyResourceAccess(
            "User does not have permission to revoke access to this collection."
        )
    target_user = await auth_queries.get_user(session, target_user_id)
    if target_user is None:
        raise exceptions.UserNotFoundException(
            f"User with id {target_user_id!r} does not exist."
        )
    editor_scope = PottoScope.collection_editor(collection.identifier)
    viewer_scope = PottoScope.collection_viewer(collection.identifier)
    new_scopes = [
        s for s in target_user.scopes if s not in (editor_scope, viewer_scope)
    ]
    try:
        await auth_commands.update_user(
            session, target_user, UserUpdate(scopes=new_scopes)
        )
    except DatabaseError as err:
        raise exceptions.CannotModifyResourceAccess(str(err)) from err


async def grant_process_access(
    session: AsyncSession,
    granting_user: Principal,
    authorizer: PottoAuthorizer,
    target_user_id: str,
    process: "Process",
    role: str,
) -> None:
    if not await authorizer.can_edit_process(granting_user, process):
        raise exceptions.CannotModifyResourceAccess(
            "User does not have permission to grant access to this process."
        )
    target_user = await auth_queries.get_user(session, target_user_id)
    if target_user is None:
        raise exceptions.UserNotFoundException(
            f"User with id {target_user_id!r} does not exist."
        )
    editor_scope = PottoScope.process_editor(process.identifier)
    viewer_scope = PottoScope.process_viewer(process.identifier)
    new_scopes = [
        s for s in target_user.scopes if s not in (editor_scope, viewer_scope)
    ]
    if role == "editor":
        new_scopes.append(editor_scope)
    else:
        new_scopes.append(viewer_scope)
    try:
        await auth_commands.update_user(
            session, target_user, UserUpdate(scopes=new_scopes)
        )
    except DatabaseError as err:
        raise exceptions.CannotModifyResourceAccess(str(err)) from err


async def revoke_process_access(
    session: AsyncSession,
    revoking_user: Principal,
    authorizer: PottoAuthorizer,
    target_user_id: str,
    process: "Process",
) -> None:
    if not await authorizer.can_edit_process(revoking_user, process):
        raise exceptions.CannotModifyResourceAccess(
            "User does not have permission to revoke access to this collection."
        )
    target_user = await auth_queries.get_user(session, target_user_id)
    if target_user is None:
        raise exceptions.UserNotFoundException(
            f"User with id {target_user_id!r} does not exist."
        )
    editor_scope = PottoScope.process_editor(process.identifier)
    viewer_scope = PottoScope.process_viewer(process.identifier)
    new_scopes = [
        s for s in target_user.scopes if s not in (editor_scope, viewer_scope)
    ]
    try:
        await auth_commands.update_user(
            session, target_user, UserUpdate(scopes=new_scopes)
        )
    except DatabaseError as err:
        raise exceptions.CannotModifyResourceAccess(str(err)) from err
