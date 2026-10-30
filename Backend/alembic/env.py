from logging.config import fileConfig

from alembic import context
from geoalchemy2 import alembic_helpers
from sqlalchemy import engine_from_config, pool

from raw import models  # noqa: F401  (importing registers every table on Base.metadata)
from raw.config import settings
from raw.database import Base

config = context.config

# '%' must be doubled because Alembic's config parser treats it specially
config.set_main_option(
    "sqlalchemy.url", 
    (settings.database_url_direct or settings.database_url).replace("%", "%%")
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # PostGIS owns this table; never let autogenerate try to drop it
    if type_ == "table" and name == "spatial_ref_sys":
        return False
    return alembic_helpers.include_object(obj, name, type_, reflected, compare_to)


def _configure_kwargs():
    return dict(
        target_metadata=target_metadata,
        compare_type=True,
        include_object=include_object,
        process_revision_directives=alembic_helpers.writer,
        render_item=alembic_helpers.render_item,
    )


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_configure_kwargs(),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, **_configure_kwargs())
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()