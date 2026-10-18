"""Quote Studio: read, edit, approve and sync quotes (the estimator's workbench)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, or_, select

from zuschlag_api.api.deps import PrincipalDep, TenantDb
from zuschlag_api.api.routes.quotes import (
    QuoteOut,
    get_llm_client,
    item_tree,
    pipeline_config,
    quote_fields,
)
from zuschlag_api.api.routes.sap import get_embedder
from zuschlag_api.core.config import Settings, get_settings
from zuschlag_api.embeddings import Embedder, EmbeddingError
from zuschlag_api.llm.client import ComplianceError, LLMOutputError, ZeroRetentionLLMClient
from zuschlag_api.models import (
    Customer,
    MatchStatus,
    Quote,
    QuoteAuditTrail,
    QuoteItem,
    QuoteStatus,
    Rfq,
    RfqSource,
)
from zuschlag_api.quoting.export import (
    ExportBlockedError,
    PreviewMismatchError,
    export_blockers,
    prepare_reqote,
    send_reqote,
)
from zuschlag_api.quoting.service import (
    QuoteLockedError,
    QuoteNotFoundError,
    agreed_payment_terms,
)
from zuschlag_api.quoting.studio import (
    ApprovalBlockedError,
    ItemEditError,
    ItemNotFoundError,
    ItemPatch,
    approve_blockers,
    approve_quote,
    catalog_warnings,
    edit_item,
    linked_materials,
)
from zuschlag_api.rfq.pipeline import QuotePipeline
from zuschlag_api.sap.transport import (
    SapRejectedError,
    SapTransport,
    TransportError,
    TransportKind,
    get_sap_transport,
)

router = APIRouter(prefix="/api/v1/quotes", tags=["quote studio"])


SapTransportDep = Annotated[SapTransport | None, Depends(get_sap_transport)]

# --------------------------------------------------------------------------- #
# Response models
# --------------------------------------------------------------------------- #


class QuoteSummary(BaseModel):
    id: uuid.UUID
    quote_number: str
    status: QuoteStatus
    customer_name: str | None
    kunnr: str | None
    rfq_subject: str | None
    currency: str
    margin_pct: Decimal
    net_total: Decimal
    gross_total: Decimal
    items: int
    review_items: int
    requested_delivery_date: date | None
    created_at: datetime
    updated_at: datetime


class QuoteList(BaseModel):
    items: list[QuoteSummary]
    total: int


class RfqSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: RfqSource
    subject: str
    customer_ref: str | None
    body_text: str | None
    attachment_object_key: str | None
    received_at: datetime


class QuoteCustomer(BaseModel):
    id: uuid.UUID
    kunnr: str
    name1: str
    name2: str | None
    street: str | None
    postal_code: str | None
    city: str | None
    country: str | None
    agreed_payment_terms: list[str]


class TrailEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp_utc: datetime
    actor_id: str
    event: str
    details: dict[str, Any] | None


class QuoteDetail(QuoteOut):
    vat_rate: Decimal | None
    vat_amount: Decimal
    gross_total: Decimal
    payment_terms: str | None
    calculated_at: datetime | None
    last_idoc_docnum: str | None
    exported_at: datetime | None
    created_at: datetime
    updated_at: datetime
    rfq: RfqSourceOut | None
    customer: QuoteCustomer | None
    trail: list[TrailEvent]
    approve_blockers: list[str] = Field(description="Why the quote cannot be approved yet")
    export_blockers: list[str] = Field(description="Why it cannot be synced to SAP yet")
    sap_transport: TransportKind | None = Field(
        description="How a sync reaches SAP; null = no outbound transport configured"
    )


async def build_detail(
    db: TenantDb, quote_id: uuid.UUID, transport: SapTransport | None
) -> QuoteDetail:
    # populate_existing: values the database computed during this request (updated_at) are reloaded.
    quote = await db.scalar(
        select(Quote).where(Quote.id == quote_id).execution_options(populate_existing=True)
    )
    if quote is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"quote {quote_id} not found")
    items = list(
        await db.scalars(
            select(QuoteItem)
            .where(QuoteItem.quote_id == quote_id)
            .order_by(QuoteItem.parent_item_id.nulls_first(), QuoteItem.position)
            .execution_options(populate_existing=True)
        )
    )
    warnings = catalog_warnings(items, await linked_materials(db, items))
    rfq = await db.scalar(select(Rfq).where(Rfq.id == quote.rfq_id)) if quote.rfq_id else None
    customer = (
        await db.scalar(select(Customer).where(Customer.id == quote.customer_id))
        if quote.customer_id
        else None
    )
    trail = await db.scalars(
        select(QuoteAuditTrail)
        .where(QuoteAuditTrail.quote_id == quote_id)
        .order_by(QuoteAuditTrail.id)
    )
    return QuoteDetail(
        **quote_fields(QuoteDetail, quote),
        items=item_tree(items, warnings),
        rfq=RfqSourceOut.model_validate(rfq) if rfq else None,
        customer=QuoteCustomer(
            id=customer.id,
            kunnr=customer.kunnr,
            name1=customer.name1,
            name2=customer.name2,
            street=customer.street,
            postal_code=customer.postal_code,
            city=customer.city,
            country=customer.country,
            agreed_payment_terms=await agreed_payment_terms(db, customer.id),
        )
        if customer
        else None,
        trail=[TrailEvent.model_validate(t) for t in trail],
        approve_blockers=approve_blockers(quote, items),
        export_blockers=(
            ["quote is already synced to SAP"]
            if quote.status is QuoteStatus.SYNCED
            else await export_blockers(db, quote, items)
        ),
        sap_transport=transport.kind if transport else None,
    )


def _not_found(exc: Exception, what: str = "quote") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} {exc} not found")


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #


@router.get("")
async def list_quotes(
    db: TenantDb,
    status_: Annotated[QuoteStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> QuoteList:
    """Quotes, newest first. `q` searches quote number, customer and RFQ subject."""
    top = QuoteItem.parent_item_id.is_(None)
    items = (
        select(func.count())
        .where(QuoteItem.quote_id == Quote.id, top)
        .correlate(Quote)
        .scalar_subquery()
    )
    review = (
        select(func.count())
        .where(
            QuoteItem.quote_id == Quote.id,
            QuoteItem.match_status == MatchStatus.NEEDS_HUMAN_REVIEW,
        )
        .correlate(Quote)
        .scalar_subquery()
    )
    stmt = (
        select(Quote, Customer.kunnr, Rfq.subject, items.label("n"), review.label("r"))
        .outerjoin(Customer, Customer.id == Quote.customer_id)
        .outerjoin(Rfq, Rfq.id == Quote.rfq_id)
    )
    if status_ is not None:
        stmt = stmt.where(Quote.status == status_)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Quote.quote_number.ilike(like),
                Quote.customer_name.ilike(like),
                Customer.kunnr.ilike(like),
                Rfq.subject.ilike(like),
            )
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await db.execute(stmt.order_by(Quote.created_at.desc()).limit(limit).offset(offset))
    return QuoteList(
        total=total or 0,
        items=[
            QuoteSummary(
                id=quote.id,
                quote_number=quote.quote_number,
                status=quote.status,
                customer_name=quote.customer_name,
                kunnr=kunnr,
                rfq_subject=subject,
                currency=quote.currency,
                margin_pct=quote.margin_pct,
                net_total=quote.net_total,
                gross_total=quote.gross_total,
                items=n,
                review_items=r,
                requested_delivery_date=quote.requested_delivery_date,
                created_at=quote.created_at,
                updated_at=quote.updated_at,
            )
            for quote, kunnr, subject, n, r in rows
        ],
    )


@router.get("/{quote_id}")
async def get_quote(quote_id: uuid.UUID, db: TenantDb, transport: SapTransportDep) -> QuoteDetail:
    """Everything the Quote Studio shows: source RFQ, BOM tree with catalog
    warnings, totals, audit trail, and what still blocks approval and sync."""
    return await build_detail(db, quote_id, transport)


# --------------------------------------------------------------------------- #
# Edit and approve
# --------------------------------------------------------------------------- #


class ItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: Decimal | None = Field(default=None, gt=0, max_digits=15, decimal_places=3)
    matnr: str | None = Field(
        default=None, max_length=40, description="SAP material number; null unlinks"
    )
    description: str | None = Field(default=None, min_length=1, max_length=300)
    uom: str | None = Field(default=None, pattern=r"^[A-Za-z0-9]{2,3}$")
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=4)


@router.patch("/{quote_id}/items/{item_id}")
async def update_item(
    quote_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ItemUpdate,
    principal: PrincipalDep,
    db: TenantDb,
    transport: SapTransportDep,
) -> QuoteDetail:
    """Inline edit of one BOM line. Costs roll up to the custom-build parent,
    the quote is repriced at its current Zuschlag, and an approved quote
    returns to draft."""
    fields = frozenset(body.model_fields_set)
    if not fields:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "nothing to change")
    try:
        await edit_item(
            db,
            quote_id,
            item_id,
            ItemPatch(fields=fields, **body.model_dump(include=set(fields))),
            actor_id=principal.actor_id,
            ip_sha256=principal.ip_sha256,
        )
    except QuoteNotFoundError as exc:
        raise _not_found(exc) from exc
    except ItemNotFoundError as exc:
        raise _not_found(exc, "item") from exc
    except QuoteLockedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ItemEditError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return await build_detail(db, quote_id, transport)


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str | None = Field(default=None, max_length=500)


@router.post("/{quote_id}/approve")
async def approve(
    quote_id: uuid.UUID,
    principal: PrincipalDep,
    db: TenantDb,
    transport: SapTransportDep,
    body: ApproveRequest | None = None,
) -> QuoteDetail:
    """Release the quote. Refused (422, every reason listed) while it is not
    calculated, a line is unpriced or an SAP match still needs human review."""
    try:
        await approve_quote(
            db,
            quote_id,
            actor_id=principal.actor_id,
            ip_sha256=principal.ip_sha256,
            comment=body.comment if body else None,
        )
    except QuoteNotFoundError as exc:
        raise _not_found(exc) from exc
    except QuoteLockedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ApprovalBlockedError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"message": "quote cannot be approved yet", "reasons": exc.reasons},
        ) from exc
    return await build_detail(db, quote_id, transport)


@router.post("/{quote_id}/reparse", status_code=status.HTTP_201_CREATED)
async def reparse(
    quote_id: uuid.UUID,
    principal: PrincipalDep,
    db: TenantDb,
    settings: Annotated[Settings, Depends(get_settings)],
    llm: Annotated[ZeroRetentionLLMClient | None, Depends(get_llm_client)],
    embedder: Annotated[Embedder | None, Depends(get_embedder)],
    transport: SapTransportDep,
) -> QuoteDetail:
    """Run extraction and matching again on the quote's source RFQ. The result
    is a *new* quote linked to the same RFQ; the old one stays unchanged, as the
    audit trail requires, and records which quote superseded it."""
    old = await db.scalar(select(Quote).where(Quote.id == quote_id))
    if old is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"quote {quote_id} not found")
    rfq = await db.scalar(select(Rfq).where(Rfq.id == old.rfq_id)) if old.rfq_id else None
    if rfq is None or not rfq.body_text:
        raise HTTPException(status.HTTP_409_CONFLICT, "quote has no source RFQ text to re-parse")
    if llm is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "LLM extraction is not configured (LLM_PROVIDER)"
        )
    pipeline = QuotePipeline(db, llm=llm, embedder=embedder, config=pipeline_config(settings))
    try:
        new = await pipeline.generate(
            rfq.body_text,
            actor_id=principal.actor_id,
            ip_sha256=principal.ip_sha256,
            customer_ref=str(old.customer_id) if old.customer_id else None,
            margin_pct=old.margin_pct,
            rfq=rfq,
        )
    except ComplianceError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except (LLMOutputError, ValidationError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"LLM extraction failed: {exc}") from exc
    except EmbeddingError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "embedding backend unavailable"
        ) from exc
    db.add(
        QuoteAuditTrail(
            quote_id=old.id,
            actor_id=principal.actor_id[:128],
            event="quote.superseded",
            details={"by_quote_id": str(new.id), "by_quote_number": new.quote_number},
        )
    )
    await db.flush()
    return await build_detail(db, new.id, transport)


# --------------------------------------------------------------------------- #
# SAP sync: preview the exact IDoc, then send exactly that
# --------------------------------------------------------------------------- #


class IdocPreview(BaseModel):
    docnum: str = Field(description="IDoc number reserved for this payload")
    sha256: str = Field(description="SHA-256 of `xml`; echo it back to /send")
    xml: str = Field(description="The exact ORDERS05/REQOTE payload (UTF-8, CRLF)")
    receiver: str
    transport: TransportKind | None


class SendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    docnum: str = Field(pattern=r"^\d{16}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SapAckStatus(BaseModel):
    docnum: str
    status: str = Field(description="06 received and valid · 53 posted · 51 error")
    text: str | None
    object_key: str | None = Field(description="SAP document created (status 53)")


class SendResult(BaseModel):
    docnum: str
    sha256: str
    transport: TransportKind
    reference: str
    sent_at: datetime
    sap_status: list[SapAckStatus] = Field(description="SAP's ALEAUD acknowledgement, if any")
    quote: QuoteDetail


def _blocked(exc: ExportBlockedError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {"message": "quote not ready for SAP", "reasons": exc.reasons},
    )


@router.post("/{quote_id}/sap-idoc/prepare")
async def prepare_idoc(
    quote_id: uuid.UUID, principal: PrincipalDep, db: TenantDb, transport: SapTransportDep
) -> IdocPreview:
    """Reserve a DOCNUM and render the IDoc for review. Nothing is sent."""
    try:
        export = await prepare_reqote(db, quote_id, actor_id=principal.actor_id)
    except QuoteNotFoundError as exc:
        raise _not_found(exc) from exc
    except QuoteLockedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ExportBlockedError as exc:
        raise _blocked(exc) from exc
    trail = await db.scalar(
        select(QuoteAuditTrail)
        .where(QuoteAuditTrail.quote_id == quote_id, QuoteAuditTrail.event == "sap.idoc.prepared")
        .order_by(QuoteAuditTrail.id.desc())
        .limit(1)
    )
    receiver = str(trail.details.get("receiver", "")) if trail and trail.details else ""
    return IdocPreview(
        docnum=export.docnum,
        sha256=export.sha256,
        xml=export.xml.decode("utf-8"),
        receiver=receiver,
        transport=transport.kind if transport else None,
    )


@router.post("/{quote_id}/sap-idoc/send")
async def send_idoc(
    quote_id: uuid.UUID,
    body: SendRequest,
    principal: PrincipalDep,
    db: TenantDb,
    transport: SapTransportDep,
) -> SendResult:
    """Send the previewed IDoc. 409 if the quote changed since the preview
    (the payload would differ from what was reviewed)."""
    if transport is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "no SAP outbound transport configured (SAP_OUTBOUND_TRANSPORT)",
        )
    try:
        delivery = await send_reqote(
            db,
            quote_id,
            docnum=body.docnum,
            expected_sha256=body.sha256,
            transport=transport,
            actor_id=principal.actor_id,
            ip_sha256=principal.ip_sha256,
        )
    except QuoteNotFoundError as exc:
        raise _not_found(exc) from exc
    except QuoteLockedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except PreviewMismatchError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ExportBlockedError as exc:
        raise _blocked(exc) from exc
    except SapRejectedError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            {"message": str(exc), "reasons": exc.reasons},
        ) from exc
    except TransportError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return SendResult(
        docnum=delivery.export.docnum,
        sha256=delivery.export.sha256,
        transport=delivery.transport,
        reference=delivery.reference,
        sent_at=delivery.sent_at,
        sap_status=[
            SapAckStatus(docnum=s.docnum, status=s.status, text=s.text, object_key=s.object_key)
            for s in delivery.sap_statuses
        ],
        quote=await build_detail(db, quote_id, transport),
    )
