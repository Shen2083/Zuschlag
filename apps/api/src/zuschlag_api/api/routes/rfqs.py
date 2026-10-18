from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from zuschlag_api.api.deps import PrincipalDep, TenantDb
from zuschlag_api.audit.service import record_audit
from zuschlag_api.models import Rfq, RfqSource, RfqStatus

router = APIRouter(prefix="/v1/rfqs", tags=["rfqs"])


class RfqCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: RfqSource = RfqSource.MANUAL
    subject: str = Field(min_length=1, max_length=300)
    customer_ref: str | None = Field(default=None, max_length=35)
    body_text: str | None = Field(default=None, max_length=200_000)


class RfqOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: RfqSource
    status: RfqStatus
    subject: str
    customer_ref: str | None
    received_at: datetime


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_rfq(body: RfqCreate, principal: PrincipalDep, db: TenantDb) -> RfqOut:
    rfq = Rfq(**body.model_dump())
    db.add(rfq)
    await db.flush()
    await db.refresh(rfq)
    await record_audit(
        db,
        actor_id=principal.actor_id,
        action="rfq.created",
        entity_type="rfq",
        entity_id=rfq.id,
        ip_sha256=principal.ip_sha256,
        context={"source": rfq.source.value},
    )
    return RfqOut.model_validate(rfq)


@router.get("")
async def list_rfqs(db: TenantDb, limit: int = 50) -> list[RfqOut]:
    rows = await db.scalars(select(Rfq).order_by(Rfq.received_at.desc()).limit(min(limit, 200)))
    return [RfqOut.model_validate(r) for r in rows]
