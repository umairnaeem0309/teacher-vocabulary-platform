"""Alembic environment wired to application settings and model metadata.

Uses the same DATABASE_URL as the application (12-factor; no duplicated
config in alembic.ini). All models must be imported here so autogenerate
sees the full metadata.
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import URL

# Make the `app` package importable when alembic runs from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.settings import get_settings  # noqa: E402
from app.db.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Full model metadata for autogenerate.
target_metadata = Base.metadata


def _database_url() -> str:
    """Resolve the sync SQLAlchemy URL for migrations.

    Precedence: explicit programmatic override (config.attributes, used by
    tests to run against a scratch database), then ALEMBIC_DATABASE_URL,
    then application settings. Tests must never downgrade the development
    database, so an isolated target is always available.
    """
    override = context.config.attributes.get("sqlalchemy_url")
    if override is not None:
        # str(URL) masks the password (***), which would break the engine;
        # render with credentials intact.
        if isinstance(override, URL):
            return override.render_as_string(hide_password=False)
        return str(override)
    env_override = os.getenv("ALEMBIC_DATABASE_URL")
    if env_override:
        return env_override
    # Alembic runs synchronously; psycopg3 dialect is already sync-capable.
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Generate SQL script without a live DB connection."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
