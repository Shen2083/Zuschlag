from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, true

from zuschlag_api.api.deps import PrincipalDep, TenantDb
from zuschlag_api.audit.service import record_audit
from zuschlag_api.models import Quote, QuoteStatus, Rfq, RfqSource, RfqStatus

router = APIRouter(prefix="/api/v1/rfqs", tags=["rfqs"])


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


class LinkedQuote(BaseModel):
    id: uuid.UUID
    quote_number: str
    status: QuoteStatus
    net_total: Decimal
    currency: str


class RfqInboxItem(RfqOut):
    preview: str | None = Field(description="First 240 characters of the inquiry")
    quote: LinkedQuote | None = Field(description="Latest quote generated from this RFQ")


@router.get("")
async def list_rfqs(
    db: TenantDb, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[RfqInboxItem]:
    """Inbound RFQs, newest first, each with the latest quote generated from it."""
    latest = (
        select(Quote)
        .where(Quote.rfq_id == Rfq.id)
        .order_by(Quote.created_at.desc())
        .limit(1)
        .correlate(Rfq)
        .lateral()
    )
    rows = await db.execute(
        select(
            Rfq,
            latest.c.id,
            latest.c.quote_number,
            latest.c.status,
            latest.c.net_total,
            latest.c.currency,
        )
        .outerjoin(latest, true())
        .order_by(Rfq.received_at.desc())
        .limit(limit)
    )
    out: list[RfqInboxItem] = []
    for rfq, qid, number, qstatus, net, currency in rows:
        out.append(
            RfqInboxItem(
                **RfqOut.model_validate(rfq).model_dump(),
                preview=(rfq.body_text or "")[:240] or None,
                quote=LinkedQuote(
                    id=qid, quote_number=number, status=qstatus, net_total=net, currency=currency
                )
                if qid
                else None,
            )
        )
    return out
