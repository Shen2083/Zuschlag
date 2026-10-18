"""Async Alembic environment.

Runs as the schema owner (MIGRATIONS_DATABASE_URL), never as the runtime role.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from zuschlag_api import models  # noqa: F401  (registers tables)
from zuschlag_api.core.config import get_settings
from zuschlag_api.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def _url() -> str:
    explicit = os.environ.get("MIGRATIONS_DATABASE_URL")
    if explicit:
        return explicit
    settings = get_settings()
    if settings.migrations_database_url is None:
        raise RuntimeError("MIGRATIONS_DATABASE_URL is not set")
    return settings.migrations_database_url.get_secret_value()


def _include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    # pgvector's HNSW index options are not reflected reliably; skip it in autogenerate diffs.
    return not (type_ == "index" and name == "ix_materials_embedding_hnsw")


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=_include_object,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url(), poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
