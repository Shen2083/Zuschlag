"""Async engine and tenant-scoped sessions.

Every tenant session binds `app.current_tenant` with `set_config(..., is_local
=> true)` at the start of *each* transaction. The setting is therefore scoped to
that transaction and can never leak to the next user of a pooled connection.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, SessionTransaction

from zuschlag_api.core.config import Settings, get_settings
from zuschlag_api.db import guards

TENANT_KEY = "tenant_id"
SYSTEM_KEY = "system"

_SET_TENANT = text("SELECT set_config('app.current_tenant', :tenant_id, true)")


def build_engine(url: str, settings: Settings) -> AsyncEngine:
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        connect_args={
            "server_settings": {
                "application_name": "zuschlag-api",
                "timezone": "UTC",
                "statement_timeout": str(settings.db_statement_timeout_ms),
            }
        },
    )


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return build_engine(settings.database_url.get_secret_value(), settings)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return make_sessionmaker(get_engine())


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@event.listens_for(Session, "after_begin")
def _bind_tenant_to_transaction(
    session: Session, transaction: SessionTransaction, connection: Connection
) -> None:
    tenant_id = session.info.get(TENANT_KEY)
    if tenant_id is not None:
        connection.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})


guards.install(Session, tenant_key=TENANT_KEY, system_key=SYSTEM_KEY)


@asynccontextmanager
async def tenant_session(
    tenant_id: uuid.UUID,
    *,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncIterator[AsyncSession]:
    """A session whose every statement runs as `tenant_id`; commits on success."""
    factory = sessionmaker or get_sessionmaker()
    info: dict[str, Any] = {TENANT_KEY: tenant_id}
    async with factory(info=info) as session, session.begin():
        yield session


@asynccontextmanager
async def system_session(
    *, sessionmaker: async_sessionmaker[AsyncSession] | None = None
) -> AsyncIterator[AsyncSession]:
    """Session without a tenant (health checks, tenant provisioning).

    RLS still applies at the database: without `app.current_tenant` no tenant
    row is visible. The flag only lifts the ORM guard for these explicit uses.
    """
    factory = sessionmaker or get_sessionmaker()
    async with factory(info={SYSTEM_KEY: True}) as session, session.begin():
        yield session
