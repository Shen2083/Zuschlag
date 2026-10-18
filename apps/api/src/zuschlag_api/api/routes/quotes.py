"""POST /api/v1/quotes/generate-from-rfq — unstructured inquiry -> priced, SAP-linked quote."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from zuschlag_api.api.deps import PrincipalDep, TenantDb
from zuschlag_api.api.routes.sap import get_embedder
from zuschlag_api.core.config import Settings, get_settings
from zuschlag_api.embeddings import Embedder, EmbeddingError
from zuschlag_api.llm.client import ComplianceError, LLMOutputError, ZeroRetentionLLMClient
from zuschlag_api.llm.providers import provider_from_settings
from zuschlag_api.models import MatchStatus, QuoteItem, QuoteItemKind, QuoteStatus, Sourcing
from zuschlag_api.quoting.calculation import VatRate
from zuschlag_api.quoting.export import ExportBlockedError, export_reqote
from zuschlag_api.quoting.payment_terms import PaymentTermsError
from zuschlag_api.quoting.service import QuoteLockedError, QuoteNotFoundError, recalculate_quote
from zuschlag_api.rfq.matching import MatchConfig
from zuschlag_api.rfq.pipeline import CustomerNotFoundError, PipelineConfig, QuotePipeline
from zuschlag_api.rfq.pricing import LaborRates

router = APIRouter(prefix="/api/v1/quotes", tags=["quotes"])


@lru_cache
def get_llm_client() -> ZeroRetentionLLMClient | None:
    provider = provider_from_settings(get_settings())
    return ZeroRetentionLLMClient(provider) if provider else None


def pipeline_config(settings: Settings) -> PipelineConfig:
    return PipelineConfig(
        match=MatchConfig(
            review_threshold=settings.rfq_review_threshold,
            dense_floor=settings.rfq_dense_floor,
            dense_ceiling=settings.rfq_dense_ceiling,
            lexical_floor=settings.rfq_lexical_floor,
            lexical_ceiling=settings.rfq_lexical_ceiling,
        ),
        suggestion_floor=settings.rfq_suggestion_floor,
        margin_pct=settings.quote_default_margin_pct,
        labor=LaborRates(settings.labor_rates_eur, settings.labor_default_rate_eur),
        default_currency=settings.quote_default_currency,
    )


class GenerateFromRfq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(
        min_length=1, description="Inquiry text or e-mail body (German or English)"
    )
    customer_id: str | None = Field(
        default=None, max_length=64, description="Customer UUID or SAP customer number (KUNNR)"
    )
    margin_pct: Decimal | None = Field(
        default=None, ge=0, lt=1000, description="Override the default Zuschlag"
    )


class QuoteItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    kind: QuoteItemKind
    description: str
    specs: list[dict[str, Any]]
    quantity: Decimal
    quantity_per_parent: Decimal | None
    uom: str
    matnr: str | None
    material_type: str | None
    match_status: MatchStatus
    match_confidence: Decimal | None
    match_method: str | None
    match_candidates: list[dict[str, Any]]
    sourcing: Sourcing
    unit_cost: Decimal | None
    labor_hours: Decimal | None
    labor_rate: Decimal | None
    extended_cost: Decimal | None
    margin_pct: Decimal | None
    unit_margin: Decimal | None
    unit_price: Decimal | None
    line_total: Decimal | None
    components: list[QuoteItemOut] = []


class QuoteOut(BaseModel):
    id: uuid.UUID
    quote_number: str
    status: QuoteStatus
    needs_review: bool
    review_reasons: list[str]
    rfq_id: uuid.UUID | None
    customer_id: uuid.UUID | None
    customer_name: str | None
    contact_name: str | None
    contact_email: str | None
    requested_delivery_date: date | None
    language: str | None
    currency: str
    margin_pct: Decimal
    material_cost: Decimal
    labor_hours: Decimal
    labor_cost: Decimal
    total_cost: Decimal
    net_total: Decimal
    llm_model: str | None
    llm_compliance_hash: str | None
    extraction: dict[str, Any] | None
    items: list[QuoteItemOut]


@router.post("/generate-from-rfq", status_code=status.HTTP_201_CREATED)
async def generate_from_rfq(
    body: GenerateFromRfq,
    principal: PrincipalDep,
    db: TenantDb,
    settings: Annotated[Settings, Depends(get_settings)],
    llm: Annotated[ZeroRetentionLLMClient | None, Depends(get_llm_client)],
    embedder: Annotated[Embedder | None, Depends(get_embedder)],
) -> QuoteOut:
    """Extract a structured BOM from the inquiry, match it against the SAP
    material master and return a priced draft quote. Items below the confidence
    threshold are flagged NEEDS_HUMAN_REVIEW and the quote is `needs_review`."""
    if len(body.raw_text) > settings.rfq_max_chars:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"raw_text exceeds {settings.rfq_max_chars} characters",
        )
    if llm is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "LLM extraction is not configured (LLM_PROVIDER)"
        )

    pipeline = QuotePipeline(db, llm=llm, embedder=embedder, config=pipeline_config(settings))
    try:
        quote = await pipeline.generate(
            body.raw_text,
            actor_id=principal.actor_id,
            ip_sha256=principal.ip_sha256,
            customer_ref=body.customer_id,
            margin_pct=body.margin_pct,
        )
    except CustomerNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"customer {exc} not found") from exc
    except ComplianceError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except (LLMOutputError, ValidationError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"LLM extraction failed: {exc}") from exc
    except EmbeddingError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "embedding backend unavailable"
        ) from exc

    items = list(
        await db.scalars(
            select(QuoteItem)
            .where(QuoteItem.quote_id == quote.id)
            .order_by(QuoteItem.parent_item_id.nulls_first(), QuoteItem.position)
        )
    )
    # Column attributes only: touching the `items` relationship would lazy-load (no IO here).
    scalar_fields = QuoteOut.model_fields.keys() - {"items", "needs_review"}
    return QuoteOut(
        **{f: getattr(quote, f) for f in scalar_fields},
        needs_review=quote.status is QuoteStatus.NEEDS_REVIEW,
        items=_tree(items),
    )


def _tree(items: list[QuoteItem]) -> list[QuoteItemOut]:
    nodes = {i.id: QuoteItemOut.model_validate(i) for i in items}
    roots: list[QuoteItemOut] = []
    for i in items:
        if i.parent_item_id is None:
            roots.append(nodes[i.id])
        else:
            nodes[i.parent_item_id].components.append(nodes[i.id])
    return roots


# --------------------------------------------------------------------------- #
# Calculation (Zuschlagskalkulation)
# --------------------------------------------------------------------------- #


class CalculateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zuschlag_pct: Decimal = Field(ge=0, le=100, description="Zuschlag on Herstellkosten, 0-100 %")
    vat_rate: Literal[19, 7] = Field(default=19, description="MwSt: 19 % standard or 7 % reduced")
    payment_terms: str | None = Field(
        default=None,
        max_length=4,
        description="SAP ZTERM, e.g. NT30; default: the customer's agreed terms",
    )
    allow_terms_deviation: bool = Field(
        default=False, description="Accept terms that differ from the customer's agreed ZTERM"
    )


class CalculatedLine(BaseModel):
    position: int
    quantity: Decimal
    unit_cost: Decimal
    material_cost: Decimal
    labor_cost: Decimal
    factory_cost: Decimal
    zuschlag_pct: Decimal
    unit_zuschlag: Decimal
    unit_price: Decimal
    net_amount: Decimal


class PaymentTermsOut(BaseModel):
    zterm: str
    net_days: int
    description_de: str
    description_en: str
    agreed: list[str]
    deviation: bool


class CalculationOut(BaseModel):
    quote_id: uuid.UUID
    quote_number: str
    currency: str
    material_cost: Decimal = Field(description="Materialkosten")
    labor_cost: Decimal = Field(description="Fertigungslohnkosten")
    factory_cost: Decimal = Field(description="Herstellkosten")
    zuschlag_pct: Decimal
    zuschlag_amount: Decimal
    net_amount: Decimal = Field(description="Nettobetrag")
    vat_rate: Decimal
    vat_amount: Decimal = Field(description="Mehrwertsteuer")
    gross_amount: Decimal = Field(description="Bruttobetrag")
    payment_terms: PaymentTermsOut
    complete: bool
    missing_price_positions: list[int]
    lines: list[CalculatedLine]


@router.post("/{quote_id}/calculate")
async def calculate_quote(
    quote_id: uuid.UUID,
    body: CalculateRequest,
    principal: PrincipalDep,
    db: TenantDb,
    settings: Annotated[Settings, Depends(get_settings)],
) -> CalculationOut:
    """Recalculate Herstellkosten -> Zuschlag -> Netto -> MwSt -> Brutto and
    validate the payment terms against the customer's ZTERM in SAP."""
    try:
        result = await recalculate_quote(
            db,
            quote_id,
            zuschlag_pct=body.zuschlag_pct,
            vat_rate=VatRate.from_percent(body.vat_rate),
            payment_terms=body.payment_terms,
            allow_terms_deviation=body.allow_terms_deviation,
            default_payment_terms=settings.quote_default_payment_terms,
            payment_terms_catalog=settings.payment_terms_catalog,
            actor_id=principal.actor_id,
        )
    except QuoteNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"quote {exc} not found") from exc
    except QuoteLockedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except PaymentTermsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    calc, quote, terms = result.calculation, result.quote, result.terms
    return CalculationOut(
        quote_id=quote.id,
        quote_number=quote.quote_number,
        currency=quote.currency,
        material_cost=calc.material_cost,
        labor_cost=calc.labor_cost,
        factory_cost=calc.factory_cost,
        zuschlag_pct=calc.zuschlag_pct,
        zuschlag_amount=calc.zuschlag_amount,
        net_amount=calc.net_amount,
        vat_rate=calc.vat_rate.value,
        vat_amount=calc.vat_amount,
        gross_amount=calc.gross_amount,
        payment_terms=PaymentTermsOut(
            zterm=terms.terms.zterm,
            net_days=terms.terms.net_days,
            description_de=terms.terms.description_de,
            description_en=terms.terms.description_en,
            agreed=list(terms.agreed),
            deviation=terms.deviation,
        ),
        complete=calc.complete,
        missing_price_positions=calc.missing_price_positions,
        lines=[CalculatedLine.model_validate(line, from_attributes=True) for line in calc.lines],
    )


# --------------------------------------------------------------------------- #
# Outbound SAP IDoc
# --------------------------------------------------------------------------- #


@router.post(
    "/{quote_id}/export-sap-idoc",
    response_class=Response,
    responses={200: {"content": {"application/xml": {}}, "description": "ORDERS05 / REQOTE IDoc"}},
)
async def export_sap_idoc(quote_id: uuid.UUID, principal: PrincipalDep, db: TenantDb) -> Response:
    """Build the ORDERS05/REQOTE IDoc, validate it against the XSD and return it.
    422 lists every reason the quote cannot be sent yet."""
    try:
        export = await export_reqote(
            db, quote_id, actor_id=principal.actor_id, ip_sha256=principal.ip_sha256
        )
    except QuoteNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"quote {exc} not found") from exc
    except ExportBlockedError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"message": "quote not ready for SAP", "reasons": exc.reasons},
        ) from exc
    return Response(
        content=export.xml,
        media_type="application/xml",
        headers={
            "X-IDoc-DOCNUM": export.docnum,
            "X-Content-SHA256": export.sha256,
            "Content-Disposition": f'attachment; filename="REQOTE_{export.docnum}.xml"',
        },
    )
