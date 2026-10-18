"""Row-level security and schema guards, exercised against real PostgreSQL."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zuschlag_api.db.guards import TenancyViolationError
from zuschlag_api.db.session import system_session, tenant_session
from zuschlag_api.models import Quote, Rfq, RfqSource

pytestmark = pytest.mark.integration

Sm = async_sessionmaker[AsyncSession]


async def _create_rfq(sm: Sm, tenant_id: uuid.UUID, subject: str) -> uuid.UUID:
    async with tenant_session(tenant_id, sessionmaker=sm) as s:
        rfq = Rfq(source=RfqSource.EMAIL, subject=subject)
        s.add(rfq)
        await s.flush()
        return rfq.id


async def test_rls_hides_other_tenants_rows_even_for_raw_sql(
    sessionmaker: Sm, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    rfq_id = await _create_rfq(sessionmaker, tenant_a, "15 server racks")

    # Raw SQL bypasses the ORM guard, so only PostgreSQL RLS stands in the way.
    async with tenant_session(tenant_b, sessionmaker=sessionmaker) as s:
        found = await s.scalar(text("SELECT count(*) FROM rfqs WHERE id = :id"), {"id": rfq_id})
    assert found == 0

    async with tenant_session(tenant_a, sessionmaker=sessionmaker) as s:
        found = await s.scalar(text("SELECT count(*) FROM rfqs WHERE id = :id"), {"id": rfq_id})
    assert found == 1


async def test_no_tenant_context_sees_nothing(sessionmaker: Sm, tenant_a: uuid.UUID) -> None:
    await _create_rfq(sessionmaker, tenant_a, "visible only to A")
    async with system_session(sessionmaker=sessionmaker) as s:
        assert await s.scalar(text("SELECT count(*) FROM rfqs")) == 0
        assert await s.scalar(text("SELECT count(*) FROM tenants")) == 0


async def test_tenant_setting_does_not_leak_across_transactions(
    sessionmaker: Sm, tenant_a: uuid.UUID
) -> None:
    async with tenant_session(tenant_a, sessionmaker=sessionmaker) as s:
        conn = await s.connection()
        raw = await conn.get_raw_connection()
        pid = raw.driver_connection.get_server_pid()  # type: ignore[union-attr]
    async with system_session(sessionmaker=sessionmaker) as s:
        setting = await s.scalar(text("SELECT current_setting('app.current_tenant', true)"))
        conn = await s.connection()
        raw = await conn.get_raw_connection()
        same_conn = raw.driver_connection.get_server_pid() == pid  # type: ignore[union-attr]
    assert setting in (None, "")
    assert same_conn, "test should reuse the pooled connection to be meaningful"


async def test_rls_blocks_inserting_rows_for_another_tenant(
    sessionmaker: Sm, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_session(tenant_a, sessionmaker=sessionmaker) as s:
            await s.execute(
                text(
                    "INSERT INTO rfqs (id, tenant_id, source, status, subject) "
                    "VALUES (gen_random_uuid(), :t, 'manual', 'received', 'smuggled')"
                ),
                {"t": tenant_b},
            )


async def test_composite_fk_blocks_cross_tenant_reference(
    sessionmaker: Sm, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    rfq_of_a = await _create_rfq(sessionmaker, tenant_a, "A's RFQ")
    with pytest.raises(IntegrityError, match="fk_quotes_tenant_id_rfq_id_rfqs"):
        async with tenant_session(tenant_b, sessionmaker=sessionmaker) as s:
            s.add(Quote(rfq_id=rfq_of_a, quote_number="AN-X-1"))


async def test_orm_guard_rejects_foreign_tenant_id(
    sessionmaker: Sm, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    with pytest.raises(TenancyViolationError):
        async with tenant_session(tenant_a, sessionmaker=sessionmaker) as s:
            s.add(Rfq(tenant_id=tenant_b, source=RfqSource.MANUAL, subject="x"))


async def test_orm_guard_rejects_unscoped_queries(sessionmaker: Sm) -> None:
    async with sessionmaker() as s:
        with pytest.raises(TenancyViolationError):
            await s.scalars(select(Rfq))


async def test_orm_queries_are_scoped_to_tenant(
    sessionmaker: Sm, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    await _create_rfq(sessionmaker, tenant_a, "a1")
    await _create_rfq(sessionmaker, tenant_b, "b1")
    async with tenant_session(tenant_a, sessionmaker=sessionmaker) as s:
        subjects = set(await s.scalars(select(Rfq.subject)))
    assert subjects == {"a1"}
