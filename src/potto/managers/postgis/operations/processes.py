"""Permission-checked business logic backing ``PostgisManager``.

The functions defined in this module always return instances of potto's public,
storage-agnostic schemas (``potto.schemas.*``), never this package's private ORM
models.
"""

import datetime as dt
import logging
from typing import cast

from sqlalchemy.exc import DatabaseError
from sqlmodel.ext.asyncio.session import AsyncSession

from ....authz.authorizer import (
    PottoAuthorizer,
    Principal,
    SystemPrincipal,
)
from .... import exceptions
from ....schemas.processes import (
    Process as ProcessSchema,
    ProcessCreate,
    ProcessDeploymentStatus,
    ProcessDeploymentStatusValue,
    ProcessUpdate,
)
from ..db.queries import processes as process_queries
from ..db.commands import processes as process_commands

logger = logging.getLogger(__name__)


async def paginated_list_processes(
    session: AsyncSession,
    user: Principal | None,
    authorizer: PottoAuthorizer,
    *,
    page: int = 1,
    page_size: int = 20,
    include_total: bool = False,
    identifier_filter: str | None = None,
) -> tuple[list[ProcessSchema], int | None]:
    """Produce a paginated list of all processes that the user has access to."""
    if user is None:
        (
            public_processes,
            count,
        ) = await process_queries.paginated_list_public_processes(
            session,
            page=page,
            page_size=page_size,
            include_total=include_total,
            identifier_filter=identifier_filter,
        )
        return [i.to_potto() for i in public_processes], count
    match user:
        case SystemPrincipal():
            (
                accessible_processes,
                count,
            ) = await process_queries.paginated_list_all_processes(
                session,
                page=page,
                page_size=page_size,
                include_total=include_total,
                identifier_filter=identifier_filter,
            )
        case _:
            accessible_ids = await authorizer.get_accessible_process_identifiers(user)
            (
                accessible_processes,
                count,
            ) = await process_queries.paginated_list_user_processes(
                session,
                page=page,
                page_size=page_size,
                include_total=include_total,
                identifier_filter=identifier_filter,
                user_id=user.id,
                accessible_identifiers=accessible_ids,
            )
    return [item.to_potto() for item in accessible_processes], count


async def get_process_by_resource_identifier(
    session: AsyncSession,
    user: Principal | None,
    authorizer: PottoAuthorizer,
    identifier: str,
) -> ProcessSchema | None:
    resource = await process_queries.get_process_by_resource_identifier(
        session, identifier
    )
    if resource is None:
        return None
    process = resource.to_potto()
    if not await authorizer.can_view_process(user, process):
        return None
    return process


async def create_process(
    session: AsyncSession,
    user: Principal | None,
    authorizer: PottoAuthorizer,
    to_create: ProcessCreate,
) -> ProcessSchema:
    if not await authorizer.can_create_process(user):
        raise exceptions.CannotCreateResourceException(
            "User does not have permission to create a process."
        )
    try:
        created = await process_commands.create_process(session, to_create)
    except DatabaseError as err:
        await session.rollback()
        raise exceptions.CannotCreateResourceException(str(err)) from err
    return created.to_potto()


async def set_process_deployment_status(
    session: AsyncSession,
    user: Principal | None,
    authorizer: PottoAuthorizer,
    process: ProcessSchema,
    value: ProcessDeploymentStatusValue,
    detail: str | None = None,
) -> ProcessSchema:
    if not await authorizer.can_edit_process(user, process):
        raise exceptions.CannotUpdateResourceException(
            f"User does not have permission to edit process {process.identifier!r}."
        )
    try:
        db_process = await process_queries.get_process_by_resource_identifier(
            session, process.identifier
        )
        if db_process is None:
            raise exceptions.ResourceNotFoundException(
                f"process {process.identifier!r} not found"
            )
        updated = await process_commands.set_process_deployment_status(
            session,
            db_process,
            ProcessDeploymentStatus(
                value=value,
                detail=detail,
                definition_hash=process.get_deployment_hash(),
                changed_at=dt.datetime.now(dt.timezone.utc),
            ),
        )
        return updated.to_potto()
    except DatabaseError as err:
        raise exceptions.CannotUpdateResourceException(str(err)) from err


async def update_process(
    session: AsyncSession,
    user: Principal | None,
    authorizer: PottoAuthorizer,
    process: ProcessSchema,
    to_update: ProcessUpdate,
) -> ProcessSchema:
    if not await authorizer.can_edit_process(user, process):
        raise exceptions.CannotUpdateResourceException(
            f"User does not have permission to edit process {process.identifier!r}."
        )
    if (
        to_update.description.owner_id is not None
        and to_update.description.owner_id != process.owner.id
    ):
        if not await authorizer.can_change_process_owner(user, process):
            raise exceptions.CannotChangeResourceOwnerException(
                f"User does not have permission to change the owner of process "
                f"{process.identifier!r}."
            )
    try:
        db_process = await process_queries.get_process_by_resource_identifier(
            session, process.identifier
        )
        if db_process is None:
            raise exceptions.ResourceNotFoundException(
                f"process {process.identifier!r} not found"
            )
        updated = await process_commands.update_process(session, db_process, to_update)
        return updated.to_potto()
    except DatabaseError as err:
        raise exceptions.CannotUpdateResourceException(str(err)) from err


async def delete_process(
    session: AsyncSession,
    user: Principal,
    authorizer: PottoAuthorizer,
    identifier: str,
) -> None:
    db_process = await process_queries.get_process_by_resource_identifier(
        session, identifier
    )
    if db_process is None:
        raise exceptions.ResourceNotFoundException(
            f"process {identifier!r} does not exist."
        )
    if not await authorizer.can_edit_process(user, db_process.to_potto()):
        raise exceptions.CannotDeleteResourceException(
            f"User does not have permission to delete process {identifier!r}."
        )
    try:
        return await process_commands.delete_process(session, cast(int, db_process.id))
    except DatabaseError as err:
        raise exceptions.CannotDeleteResourceException(str(err)) from err
