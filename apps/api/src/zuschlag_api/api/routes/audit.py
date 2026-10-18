from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from zuschlag_api.api.deps import TenantDb
from zuschlag_api.audit.service import audit_chain_breaks
from zuschlag_api.models import AuditLog

router = APIRouter(prefix="/v1/audit-logs", tags=["audit"])


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    timestamp_utc: datetime
    actor_id: str
    action: str
    entity_type: str
    entity_id: str
    ip_sha256: str | None
    context: dict[str, Any] | None
    entry_hash: str


@router.get("")
async def list_audit_logs(db: TenantDb, limit: int = 100) -> list[AuditLogOut]:
    rows = await db.scalars(select(AuditLog).order_by(AuditLog.seq.desc()).limit(min(limit, 500)))
    return [AuditLogOut.model_validate(r) for r in rows]


@router.get("/verify")
async def verify_audit_chain(db: TenantDb) -> dict[str, Any]:
    breaks = await audit_chain_breaks(db)
    return {"intact": not breaks, "breaks": [{"seq": b.seq, "reason": b.reason} for b in breaks]}
