"""POST /quotes/{id}/export-sap-idoc: quote -> validated ORDERS05/REQOTE XML."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from zuschlag_api.audit.service import record_audit
from zuschlag_api.db.session import TENANT_KEY
from zuschlag_api.models import Customer, MatchStatus, QuoteAuditTrail, QuoteItem, Tenant
from zuschlag_api.quoting.service import load_quote
from zuschlag_api.sap.reqote import (
    ReqoteDocument,
    ReqoteItem,
    SapOutboundProfile,
    SoldTo,
    render_reqote,
)


class ExportBlockedError(RuntimeError):
    """The quote is not ready for SAP; `reasons` says why (all of them at once)."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


@dataclass(frozen=True, slots=True)
class IdocExport:
    docnum: str
    xml: bytes
    sha256: str


async def _profile(session: AsyncSession) -> SapOutboundProfile | None:
    tenant = await session.scalar(
        select(Tenant).where(Tenant.tenant_id == session.info[TENANT_KEY])
    )
    if tenant is None or not tenant.sap_outbound_profile:
        return None
    return SapOutboundProfile.model_validate(tenant.sap_outbound_profile)


def _items(top_level: list[QuoteItem], reasons: list[str]) -> list[ReqoteItem]:
    out: list[ReqoteItem] = []
    for item in top_level:
        label = f"Item {item.position:05d}"
        if not item.matnr:
            reasons.append(f"{label}: no SAP material number (custom build or missing in catalog)")
            continue
        if item.match_status is MatchStatus.NEEDS_HUMAN_REVIEW:
            reasons.append(f"{label}: SAP match {item.matnr} is NEEDS_HUMAN_REVIEW")
            continue
        if item.unit_price is None:
            reasons.append(f"{label}: not priced")
            continue
        try:
            out.append(
                ReqoteItem(
                    posex=item.position,
                    menge=item.quantity,
                    menee=item.uom,
                    idnlf=item.matnr,
                    ktext=item.description[:70],
                )
            )
        except ValidationError as exc:
            reasons.append(f"{label}: {exc.errors()[0]['msg']}")
    return out


def _cut(value: str | None, length: int) -> str | None:
    return value[:length] if value else None


async def export_reqote(
    session: AsyncSession, quote_id: uuid.UUID, *, actor_id: str, ip_sha256: str | None
) -> IdocExport:
    quote, items = await load_quote(session, quote_id)
    reasons: list[str] = []

    profile = await _profile(session)
    if profile is None:
        reasons.append("tenant has no SAP outbound partner profile (sap_outbound_profile)")
    if quote.payment_terms is None:
        reasons.append("quote has not been calculated (no payment terms); call /calculate first")
    customer = (
        await session.scalar(select(Customer).where(Customer.id == quote.customer_id))
        if quote.customer_id
        else None
    )
    if customer is None:
        reasons.append("quote is not linked to an SAP customer (KUNNR)")

    top_level = [i for i in items if i.parent_item_id is None]
    if not top_level:
        reasons.append("quote has no items")
    reqote_items = _items(top_level, reasons)

    if reasons:
        raise ExportBlockedError(reasons)
    assert profile is not None
    assert customer is not None
    assert quote.payment_terms is not None

    next_value = await session.scalar(text("SELECT nextval('sap_outbound_docnum_seq')"))
    docnum = f"{int(next_value or 0):016d}"
    doc = ReqoteDocument(
        docnum=docnum,
        belnr=quote.quote_number,
        curcy=quote.currency,
        zterm=quote.payment_terms,
        sold_to=SoldTo(
            partn=customer.kunnr,
            name1=customer.name1[:35],
            name2=_cut(customer.name2, 35),
            stras=_cut(customer.street, 35),
            ort01=_cut(customer.city, 35),
            pstlz=customer.postal_code or None,
            land1=customer.country or None,
        ),
        items=tuple(reqote_items),
    )
    xml = render_reqote(doc, profile)
    digest = hashlib.sha256(xml).hexdigest()

    quote.last_idoc_docnum = docnum
    quote.exported_at = datetime.now(UTC)
    session.add(
        QuoteAuditTrail(
            quote_id=quote.id,
            actor_id=actor_id[:128],
            event="sap.idoc.exported",
            details={
                "idoc_type": "ORDERS05",
                "message_type": "REQOTE",
                "docnum": docnum,
                "receiver": profile.receiver_partner,
                "items": len(reqote_items),
                "xml_sha256": digest,
            },
        )
    )
    await record_audit(
        session,
        actor_id=actor_id,
        action="sap.reqote.exported",
        entity_type="quote",
        entity_id=quote.id,
        ip_sha256=ip_sha256,
        context={"docnum": docnum, "xml_sha256": digest},
    )
    await session.flush()
    return IdocExport(docnum=docnum, xml=xml, sha256=digest)
