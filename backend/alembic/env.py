"""Alembic migration environment for HealthScope."""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from healthscope.config import get_settings
from healthscope.database import Base
from healthscope.models import (  # noqa: F401
    HospitalIngestionRun,
    HospitalSnapshot,
    HospitalSnapshotCompletion,
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    """Prefer an explicit Alembic URL, then fall back to application settings."""

    configured_url = config.get_main_option("sqlalchemy.url")
    return configured_url or get_settings().database_url


def run_migrations_offline() -> None:
    """Run migrations without creating a database connection."""

    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using a database connection."""

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
