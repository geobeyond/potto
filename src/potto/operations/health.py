import asyncio
import typing

import alembic.config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from ..schemas.system import HealthCheck


def _get_current_and_head_revisions(
    alembic_config: alembic.config.Config,
) -> tuple[set[str], set[str]]:
    script = ScriptDirectory.from_config(alembic_config)
    head_revisions = set(script.get_heads())
    # always set by build_alembic_config(), the only place that constructs
    # an alembic_config for this function
    db_url = typing.cast(str, alembic_config.get_main_option("sqlalchemy.url"))
    engine = create_engine(db_url)
    try:
        with engine.connect() as connection:
            current_revisions = set(
                MigrationContext.configure(connection).get_current_heads()
            )
    finally:
        engine.dispose()
    return current_revisions, head_revisions


async def check_health(alembic_config: alembic.config.Config) -> HealthCheck:
    """Check DB connectivity and whether it's stamped at the migrations head.

    Connects to the DB and compares its current alembic revision(s) against
    the migration scripts' head - this catches both an unreachable DB and one
    that's behind on migrations, without a separate connectivity check.

    Deliberately avoids alembic's autogenerate (e.g. ``alembic.command.check``,
    used by the CLI's ``check_for_changes``): autogenerate's diffing mutates
    shared SQLAlchemy metadata for enum-typed columns as a side effect (a bug
    in ``alembic_postgresql_enum``'s autogenerate hook, which reassigns
    ``column.type`` in place on the actual mapped ``Table`` objects rather
    than a copy, whenever it has to render a ``CreateTableOp``/``AddColumnOp``
    for one). That's tolerable for a one-off CLI command, but this check runs
    against a live, long-running server process - the first time it observes
    a missing/outdated table it would permanently corrupt that column's
    ``enum_class`` for the rest of the process's life (breaking, e.g., the
    admin UI's ``CollectionView``). A plain revision-vs-head comparison never
    touches autogenerate at all, so it can't trigger that bug - the trade-off
    is that it won't catch a DB that's stamped at head but whose live schema
    was hand-edited to no longer match the models.
    """
    try:
        current_revisions, head_revisions = await asyncio.to_thread(
            _get_current_and_head_revisions, alembic_config
        )
    except Exception:
        return HealthCheck(status="error", database="error")

    if current_revisions == head_revisions:
        return HealthCheck(status="ok", database="ok")
    return HealthCheck(status="error", database="outdated")
