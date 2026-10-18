from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession

from zuschlag_api.db.session import TENANT_KEY
from zuschlag_api.models import AuditLog


async def record_audit(
    session: AsyncSession,
    *,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID,
    ip_sha256: str | None = None,
    context: dict[str, Any] | None = None,
) -> AuditLog:
    """Append an audit entry inside the caller's transaction.

    Writing in the same transaction as the business change means the audit row
    exists if and only if the change was committed.
    """
    tenant_id = session.info.get(TENANT_KEY)
    if tenant_id is None:
        raise RuntimeError("audit entries must be written from a tenant session")
    entry = AuditLog(
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        ip_sha256=ip_sha256,
        context=context,
    )
    session.add(entry)
    await session.flush()
    await session.refresh(entry)  # pull trigger-assigned seq / hashes / timestamp
    return entry


async def audit_chain_breaks(session: AsyncSession) -> list[Row[Any]]:
    """Rows of the current tenant whose hash chain does not verify (empty = intact)."""
    tenant_id = session.info.get(TENANT_KEY)
    result = await session.execute(
        text("SELECT seq, reason FROM app.audit_chain_breaks(:tenant_id)"),
        {"tenant_id": tenant_id},
    )
    return list(result.all())
