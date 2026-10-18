"""GoBD audit log: append-only, server-stamped, hash-chained."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from zuschlag_api.audit.service import audit_chain_breaks, record_audit
from zuschlag_api.db.session import tenant_session
from zuschlag_api.llm.client import LLMMessage, LLMRequest, ZeroRetentionLLMClient
from zuschlag_api.llm.providers import FakeProvider
from zuschlag_api.main import create_app
from zuschlag_api.models import AuditLog

pytestmark = pytest.mark.integration

Sm = async_sessionmaker[AsyncSession]


async def _write(sm: Sm, tenant: uuid.UUID, n: int) -> list[AuditLog]:
    async with tenant_session(tenant, sessionmaker=sm) as s:
        return [
            await record_audit(
                s, actor_id="u1", action="quote.updated", entity_type="quote", entity_id=f"Q{i}"
            )
            for i in range(n)
        ]


async def test_entries_are_sequenced_and_chained(sessionmaker: Sm, tenant_a: uuid.UUID) -> None:
    first, second = await _write(sessionmaker, tenant_a, 2)
    assert (first.seq, second.seq) == (1, 2)
    assert first.prev_hash == "0" * 64
    assert second.prev_hash == first.entry_hash
    async with tenant_session(tenant_a, sessionmaker=sessionmaker) as s:
        assert await audit_chain_breaks(s) == []


async def test_sequences_are_per_tenant(
    sessionmaker: Sm, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    await _write(sessionmaker, tenant_a, 3)
    (b_first,) = await _write(sessionmaker, tenant_b, 1)
    assert b_first.seq == 1


async def test_client_supplied_timestamp_is_ignored(sessionmaker: Sm, tenant_a: uuid.UUID) -> None:
    backdated = datetime(1999, 1, 1, tzinfo=UTC)
    async with tenant_session(tenant_a, sessionmaker=sessionmaker) as s:
        entry = AuditLog(
            actor_id="u1", action="x", entity_type="t", entity_id="1", timestamp_utc=backdated
        )
        s.add(entry)
        await s.flush()
        await s.refresh(entry)
    assert datetime.now(UTC) - entry.timestamp_utc < timedelta(minutes=1)


@pytest.mark.parametrize(
    "statement",
    ["UPDATE audit_logs SET action = 'tampered'", "DELETE FROM audit_logs", "TRUNCATE audit_logs"],
)
async def test_runtime_role_cannot_modify(
    sessionmaker: Sm, tenant_a: uuid.UUID, statement: str
) -> None:
    await _write(sessionmaker, tenant_a, 1)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with tenant_session(tenant_a, sessionmaker=sessionmaker) as s:
            await s.execute(text(statement))


@pytest.mark.skipif(not os.environ.get("TEST_ADMIN_DATABASE_URL"), reason="needs superuser URL")
async def test_triggers_block_even_superuser_and_tampering_is_detected(
    sessionmaker: Sm, tenant_a: uuid.UUID
) -> None:
    await _write(sessionmaker, tenant_a, 3)
    admin = create_async_engine(os.environ["TEST_ADMIN_DATABASE_URL"])
    try:
        async with admin.connect() as conn:
            with pytest.raises(DBAPIError, match="append-only"):
                await conn.execute(
                    text("DELETE FROM audit_logs WHERE tenant_id = :t"), {"t": tenant_a}
                )
            await conn.rollback()

        # Simulate an out-of-band edit by someone who disables the trigger.
        async with admin.begin() as conn:
            await conn.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER audit_logs_immutable"))
            await conn.execute(
                text("UPDATE audit_logs SET actor_id = 'mallory' WHERE tenant_id = :t AND seq = 2"),
                {"t": tenant_a},
            )
            await conn.execute(text("ALTER TABLE audit_logs ENABLE TRIGGER audit_logs_immutable"))
    finally:
        await admin.dispose()

    async with tenant_session(tenant_a, sessionmaker=sessionmaker) as s:
        breaks = await audit_chain_breaks(s)
    assert [(b.seq, b.reason) for b in breaks] == [(2, "entry_hash mismatch")]


async def test_llm_call_writes_hash_only_audit_entry(sessionmaker: Sm, tenant_a: uuid.UUID) -> None:
    request = LLMRequest(messages=(LLMMessage(role="user", content="secret drawing number 4711"),))
    async with tenant_session(tenant_a, sessionmaker=sessionmaker) as s:
        result = await ZeroRetentionLLMClient(FakeProvider()).complete(
            request, tenant_id=tenant_a, actor_id="u1", audit_session=s
        )
        row = await s.scalar(
            text("SELECT context::text FROM audit_logs WHERE entity_id = :h"),
            {"h": result.compliance.compliance_hash},
        )
    assert row is not None
    assert "4711" not in row
    assert result.compliance.prompt_sha256 in row


async def test_api_create_rfq_is_audited_with_pseudonymised_ip(tenant_a: uuid.UUID) -> None:
    transport = httpx.ASGITransport(app=create_app(), client=("198.51.100.23", 50000))
    headers = {"X-Tenant-ID": str(tenant_a), "X-Actor-ID": "julia.schmidt"}
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        created = await c.post(
            "/api/v1/rfqs", json={"subject": "15 Edelstahl-Racks"}, headers=headers
        )
        assert created.status_code == 201, created.text
        logs = (await c.get("/api/v1/audit-logs", headers=headers)).json()
        verify = (await c.get("/api/v1/audit-logs/verify", headers=headers)).json()

    entry = next(e for e in logs if e["entity_id"] == created.json()["id"])
    assert entry["action"] == "rfq.created"
    assert entry["actor_id"] == "julia.schmidt"
    assert len(entry["ip_sha256"]) == 64
    assert "198.51" not in entry["ip_sha256"]
    assert verify == {"intact": True, "breaks": []}
