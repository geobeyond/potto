from logging.config import fileConfig

# DO NOT REMOVE - this import is needed in order to enjoy proper enum support
import alembic_postgresql_enum  # noqa

from sqlalchemy import create_engine
from alembic import context
from geoalchemy2 import (
    alembic_helpers,
    Geometry,
)
from sqlmodel import SQLModel

from potto.collections._postgis.db.models import ShapelyGeometryAdapter

# this import is crucial for SQLModel.metadata to be populated
# with our models, do not remove!
from potto.collections._postgis.db import models  # noqa

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = SQLModel.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def potto_render_item(type_, obj, autogen_context):
    """Render ShapelyGeometryAdapter as a plain Geometry, for migrations"""
    if type_ == "type" and isinstance(obj, ShapelyGeometryAdapter):
        geom = Geometry(
            geometry_type=obj.geometry_type, srid=obj.srid, spatial_index=False
        )
        return alembic_helpers.render_item(type_, geom, autogen_context)
    return alembic_helpers.render_item(type_, obj, autogen_context)


def include_name(name, type_, parent_names) -> bool:
    """Control which names to include in the autogeneration of migrations.

    This is used in order to exclude certain tables from being considered by alembic
    when generating migrations.
    More info:

     https://alembic.sqlalchemy.org/en/latest/autogenerate.html#omitting-table-names-from-the-autogenerate-process
    """
    if type_ == "table":
        return name in target_metadata.tables
    else:
        return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_name=include_name,
        include_object=alembic_helpers.include_object,
        process_revision_directives=alembic_helpers.writer,
        render_item=potto_render_item,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = create_engine(config.get_main_option("sqlalchemy.url"))
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=alembic_helpers.include_object,
            include_name=include_name,
            process_revision_directives=alembic_helpers.writer,
            render_item=potto_render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
