from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest

# Settings are read at import time by the app; pin a hermetic test config first.
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "TRUSTED_HOSTS": "testserver,localhost",
        "CORS_ALLOWED_ORIGINS": "http://localhost:3000",
        "AUDIT_IP_HMAC_KEY": "test-only-audit-ip-hmac-key-0123456789abcdef",
        "AUTH_MODE": "dev_headers",
        "LLM_PROVIDER": "disabled",
    }
)
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
TEST_ADMIN_DATABASE_URL = os.environ.get("TEST_ADMIN_DATABASE_URL")
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker  # noqa: E402

from zuschlag_api.core.config import get_settings  # noqa: E402
from zuschlag_api.db.session import build_engine, make_sessionmaker, tenant_session  # noqa: E402
from zuschlag_api.models import Tenant  # noqa: E402


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if TEST_DATABASE_URL:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    assert TEST_DATABASE_URL
    eng = build_engine(TEST_DATABASE_URL, get_settings())
    yield eng
    await eng.dispose()


@pytest.fixture(scope="session")
def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return make_sessionmaker(engine)


async def _new_tenant(sm: async_sessionmaker[AsyncSession], name: str) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    # Provisioning runs *as* the new tenant so the RLS WITH CHECK passes.
    async with tenant_session(tenant_id, sessionmaker=sm) as s:
        s.add(Tenant(tenant_id=tenant_id, name=name))
    return tenant_id


@pytest.fixture
async def tenant_a(sessionmaker: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    return await _new_tenant(sessionmaker, "Müller Metallbau GmbH")


@pytest.fixture
async def tenant_b(sessionmaker: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    return await _new_tenant(sessionmaker, "Schmidt Blechtechnik KG")
