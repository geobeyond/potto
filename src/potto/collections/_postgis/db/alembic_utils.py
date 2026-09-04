import alembic.config


def build_alembic_config(database_dsn: str) -> alembic.config.Config:
    """Build the alembic ``Config`` used for potto's migrations."""
    config = alembic.config.Config()
    config.set_main_option("script_location", "potto.db:migrations")
    config.set_main_option(
        "file_template",
        "%%(year)d_%%(month).2d_%%(day).2d_%%(hour).2d%%(minute).2d-%%(rev)s_%%(slug)s",
    )
    config.set_main_option("sqlalchemy.url", database_dsn)
    return config
