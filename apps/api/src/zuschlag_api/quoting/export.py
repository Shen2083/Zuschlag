"""Quote -> validated ORDERS05/REQOTE XML, and its delivery to SAP.

* ``export_reqote``: build and return the IDoc (download / manual transfer).
* ``prepare_reqote`` + ``send_reqote``: the Quote Studio flow. *prepare* numbers
  and renders the IDoc so the estimator can review the exact payload; *send*
  re-renders it, refuses if a single byte differs from what was reviewed, and
  hands it to the configured SAP transport.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from zuschlag_api.audit.service import record_audit
from zuschlag_api.db.session import TENANT_KEY
from zuschlag_api.models import (
    Customer,
    MatchStatus,
    Quote,
    QuoteAuditTrail,
    QuoteItem,
    QuoteStatus,
    Tenant,
)
from zuschlag_api.quoting.service import QuoteLockedError, load_quote
from zuschlag_api.sap.reqote import (
    ReqoteDocument,
    ReqoteItem,
    SapOutboundProfile,
    SoldTo,
    render_reqote,
)
from zuschlag_api.sap.transport import SapTransport, TransportKind


class PreviewMismatchError(RuntimeError):
    """The quote changed after its IDoc was previewed; it must be previewed again."""


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


@dataclass(frozen=True, slots=True)
class _Ready:
    profile: SapOutboundProfile
    customer: Customer
    zterm: str
    items: tuple[ReqoteItem, ...]


async def _assemble(
    session: AsyncSession, quote: Quote, items: list[QuoteItem], *, require_approval: bool
) -> tuple[_Ready | None, list[str]]:
    reasons: list[str] = []
    if require_approval and quote.status is not QuoteStatus.APPROVED:
        reasons.append(f"quote is {quote.status.value}; it must be approved before ERP sync")

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

    if reasons or profile is None or customer is None or quote.payment_terms is None:
        return None, reasons
    return _Ready(profile, customer, quote.payment_terms, tuple(reqote_items)), reasons


async def export_blockers(
    session: AsyncSession, quote: Quote, items: list[QuoteItem], *, require_approval: bool = True
) -> list[str]:
    """Why the quote cannot be synced to SAP right now (empty when it can)."""
    _, reasons = await _assemble(session, quote, items, require_approval=require_approval)
    return reasons


def _render(quote: Quote, ready: _Ready, docnum: str) -> IdocExport:
    c = ready.customer
    doc = ReqoteDocument(
        docnum=docnum,
        belnr=quote.quote_number,
        curcy=quote.currency,
        zterm=ready.zterm,
        sold_to=SoldTo(
            partn=c.kunnr,
            name1=c.name1[:35],
            name2=_cut(c.name2, 35),
            stras=_cut(c.street, 35),
            ort01=_cut(c.city, 35),
            pstlz=c.postal_code or None,
            land1=c.country or None,
        ),
        items=ready.items,
    )
    xml = render_reqote(doc, ready.profile)
    return IdocExport(docnum=docnum, xml=xml, sha256=hashlib.sha256(xml).hexdigest())


async def _next_docnum(session: AsyncSession) -> str:
    next_value = await session.scalar(text("SELECT nextval('sap_outbound_docnum_seq')"))
    return f"{int(next_value or 0):016d}"


async def _ready(
    session: AsyncSession, quote_id: uuid.UUID, *, require_approval: bool
) -> tuple[Quote, _Ready]:
    quote, items = await load_quote(session, quote_id)
    if quote.status is QuoteStatus.SYNCED and require_approval:
        raise QuoteLockedError(f"quote {quote.quote_number} is already synced to SAP")
    ready, reasons = await _assemble(session, quote, items, require_approval=require_approval)
    if ready is None:
        raise ExportBlockedError(reasons)
    return quote, ready


def _trail(quote: Quote, actor_id: str, event: str, details: dict[str, Any]) -> QuoteAuditTrail:
    return QuoteAuditTrail(
        quote_id=quote.id,
        actor_id=actor_id[:128],
        event=event,
        details={"idoc_type": "ORDERS05", "message_type": "REQOTE", **details},
    )


async def export_reqote(
    session: AsyncSession, quote_id: uuid.UUID, *, actor_id: str, ip_sha256: str | None
) -> IdocExport:
    quote, ready = await _ready(session, quote_id, require_approval=False)
    export = _render(quote, ready, await _next_docnum(session))

    quote.last_idoc_docnum = export.docnum
    quote.exported_at = datetime.now(UTC)
    session.add(
        _trail(
            quote,
            actor_id,
            "sap.idoc.exported",
            {
                "docnum": export.docnum,
                "receiver": ready.profile.receiver_partner,
                "items": len(ready.items),
                "xml_sha256": export.sha256,
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
        context={"docnum": export.docnum, "xml_sha256": export.sha256},
    )
    await session.flush()
    return export


async def prepare_reqote(
    session: AsyncSession, quote_id: uuid.UUID, *, actor_id: str
) -> IdocExport:
    """Number and render the IDoc for review. Nothing is sent."""
    quote, ready = await _ready(session, quote_id, require_approval=True)
    export = _render(quote, ready, await _next_docnum(session))
    session.add(
        _trail(
            quote,
            actor_id,
            "sap.idoc.prepared",
            {
                "docnum": export.docnum,
                "receiver": ready.profile.receiver_partner,
                "items": len(ready.items),
                "xml_sha256": export.sha256,
            },
        )
    )
    await session.flush()
    return export


@dataclass(frozen=True, slots=True)
class IdocDelivery:
    export: IdocExport
    transport: TransportKind
    reference: str
    sent_at: datetime


async def send_reqote(
    session: AsyncSession,
    quote_id: uuid.UUID,
    *,
    docnum: str,
    expected_sha256: str,
    transport: SapTransport,
    actor_id: str,
    ip_sha256: str | None,
) -> IdocDelivery:
    """Send exactly the payload that was previewed under `docnum`.

    The IDoc is rebuilt from the current quote. If it differs from the reviewed
    bytes (the quote or master data changed in between), nothing is sent."""
    quote, ready = await _ready(session, quote_id, require_approval=True)
    prepared = await session.scalar(
        select(QuoteAuditTrail)
        .where(
            QuoteAuditTrail.quote_id == quote.id,
            QuoteAuditTrail.event == "sap.idoc.prepared",
            QuoteAuditTrail.details["docnum"].astext == docnum,
        )
        .order_by(QuoteAuditTrail.id.desc())
        .limit(1)
    )
    if prepared is None or prepared.details is None:
        raise PreviewMismatchError(f"IDoc {docnum} was not prepared for this quote")
    export = _render(quote, ready, docnum)
    if export.sha256 != prepared.details["xml_sha256"] or export.sha256 != expected_sha256:
        raise PreviewMismatchError(
            "the quote changed after the IDoc preview; review the new payload before sending"
        )

    filename = f"REQOTE_{docnum}.xml"
    reference = await transport.send(filename, export.xml)
    sent_at = datetime.now(UTC)
    quote.last_idoc_docnum = docnum
    quote.exported_at = sent_at
    quote.status = QuoteStatus.SYNCED
    session.add(
        _trail(
            quote,
            actor_id,
            "sap.idoc.sent",
            {
                "docnum": docnum,
                "receiver": ready.profile.receiver_partner,
                "transport": transport.kind,
                "target": transport.target,
                "reference": reference,
                "xml_sha256": export.sha256,
            },
        )
    )
    await record_audit(
        session,
        actor_id=actor_id,
        action="sap.reqote.sent",
        entity_type="quote",
        entity_id=quote.id,
        ip_sha256=ip_sha256,
        context={"docnum": docnum, "xml_sha256": export.sha256, "transport": transport.kind},
    )
    await session.flush()
    return IdocDelivery(export, transport.kind, reference, sent_at)
