"""Alembic entry point. Runs the migrations in migrations/versions against the "worker" schema."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import SCHEMA, metadata

config = context.config

# Tests pass configure_logging=False so Alembic does not replace pytest's log capture.
if config.config_file_name and config.attributes.get("configure_logging", True):
    fileConfig(config.config_file_name)


def database_url() -> str:
    # Tests set the URL explicitly; otherwise use the app's settings (DATABASE_URL).
    url = config.attributes.get("database_url")
    if url:
        return url
    from app.config import get_settings

    return get_settings().database_url


def run_migrations(connection: Connection) -> None:
    # The schema must exist before Alembic can create its version table inside it.
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
    context.configure(
        connection=connection,
        target_metadata=metadata,
        version_table_schema=SCHEMA,  # alembic_version lives in "worker", next to our tables
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
        await connection.commit()
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (SQL script) mode is not supported; run against a database.")

asyncio.run(run_async_migrations())
