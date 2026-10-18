"""RFQ -> structured BOM -> priced quote.

    raw text --(LLM, structured output)--> RfqExtraction
             --(hybrid matcher)----------> SAP material per line / component
             --(costing)-----------------> quote + quote_items + quote_audit_trail

Everything runs in the caller's tenant transaction, so a failed step leaves
no partial quote behind.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zuschlag_api.audit.service import record_audit
from zuschlag_api.db.session import TENANT_KEY
from zuschlag_api.embeddings.base import Embedder
from zuschlag_api.llm.client import ZeroRetentionLLMClient
from zuschlag_api.models import (
    Customer,
    CustomerSalesArea,
    MatchStatus,
    Quote,
    QuoteAuditTrail,
    QuoteItem,
    QuoteItemKind,
    QuoteStatus,
    Rfq,
    RfqSource,
    RfqStatus,
    Sourcing,
)
from zuschlag_api.rfq.extraction import ExtractionResult, extract_rfq
from zuschlag_api.rfq.matching import HybridMatcher, MatchConfig, MatchResult
from zuschlag_api.rfq.pricing import (
    LaborRates,
    material_unit_cost,
    money,
    price_line,
    to_decimal,
    unit_amount,
)
from zuschlag_api.rfq.schema import BomComponent, LineItem

CUSTOMER_NAME_MIN_SIMILARITY = 0.75


class CustomerNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    match: MatchConfig
    suggestion_floor: float
    margin_pct: Decimal
    labor: LaborRates
    default_currency: str = "EUR"


@dataclass(slots=True)
class _Totals:
    material_cost: Decimal = Decimal(0)
    labor_hours: Decimal = Decimal(0)
    labor_cost: Decimal = Decimal(0)
    net_total: Decimal = Decimal(0)
    reasons: list[str] = field(default_factory=list)


def _tenant(session: AsyncSession) -> uuid.UUID:
    return session.info[TENANT_KEY]  # type: ignore[no-any-return]


async def resolve_customer(session: AsyncSession, customer_ref: str) -> Customer:
    """`customer_ref` is our customer UUID or the SAP customer number (KUNNR)."""
    try:
        cid = uuid.UUID(customer_ref)
        customer = await session.scalar(select(Customer).where(Customer.id == cid))
    except ValueError:
        kunnr = customer_ref.strip()
        kunnr = kunnr.zfill(10) if kunnr.isdigit() else kunnr  # SAP ALPHA conversion
        customer = await session.scalar(select(Customer).where(Customer.kunnr == kunnr))
    if customer is None:
        raise CustomerNotFoundError(customer_ref)
    return customer


async def _guess_customer(
    session: AsyncSession, company_name: str | None
) -> tuple[Customer | None, float]:
    if not company_name:
        return None, 0.0
    sim = func.similarity(func.lower(Customer.name1), company_name.lower())
    row = (
        await session.execute(
            select(Customer, sim.label("sim"))
            .where(Customer.is_active)
            .order_by(sim.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None, 0.0
    return row[0], float(row[1])


async def _currency_for(session: AsyncSession, customer: Customer | None, default: str) -> str:
    if customer is None:
        return default
    currency = await session.scalar(
        select(CustomerSalesArea.currency)
        .where(CustomerSalesArea.customer_id == customer.id, CustomerSalesArea.is_active)
        .order_by(CustomerSalesArea.sales_org, CustomerSalesArea.distribution_channel)
        .limit(1)
    )
    return currency or default


class QuotePipeline:
    def __init__(
        self,
        session: AsyncSession,
        *,
        llm: ZeroRetentionLLMClient,
        embedder: Embedder | None,
        config: PipelineConfig,
    ) -> None:
        self.session = session
        self.llm = llm
        self.config = config
        self.matcher = HybridMatcher(session, embedder, config.match)

    # ------------------------------------------------------------------ public

    async def generate(
        self,
        raw_text: str,
        *,
        actor_id: str,
        ip_sha256: str | None,
        customer_ref: str | None = None,
        margin_pct: Decimal | None = None,
        received_on: date | None = None,
    ) -> Quote:
        s = self.session
        tenant_id = _tenant(s)
        received_on = received_on or datetime.now(UTC).date()
        margin = self.config.margin_pct if margin_pct is None else margin_pct
        totals = _Totals()

        customer = await resolve_customer(s, customer_ref) if customer_ref else None

        rfq = Rfq(source=RfqSource.MANUAL, subject="(processing)", body_text=raw_text)
        s.add(rfq)
        await s.flush()

        extracted = await extract_rfq(
            self.llm,
            raw_text,
            received_on=received_on,
            tenant_id=tenant_id,
            actor_id=actor_id,
            audit_session=s,
        )
        ex = extracted.extraction
        rfq.subject = ex.summary[:300] or "RFQ"
        rfq.customer_ref = (ex.customer.customer_reference or "")[:35] or None
        rfq.status = RfqStatus.PARSED

        customer_match: dict[str, Any] | None = None
        if customer is None:
            guess, similarity = await _guess_customer(s, ex.customer.company_name)
            if guess is not None and similarity >= CUSTOMER_NAME_MIN_SIMILARITY:
                customer = guess
                customer_match = {"kunnr": guess.kunnr, "similarity": round(similarity, 3)}
            elif ex.customer.company_name:
                totals.reasons.append(
                    f"Customer '{ex.customer.company_name}' not found in SAP customer master"
                )

        quote = Quote(
            rfq_id=rfq.id,
            customer_id=customer.id if customer else None,
            quote_number=f"AN-{received_on:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
            status=QuoteStatus.DRAFT,
            currency=await _currency_for(s, customer, self.config.default_currency),
            margin_pct=margin,
            customer_name=ex.customer.company_name or (customer.name1 if customer else None),
            contact_name=ex.customer.contact_name,
            contact_email=ex.customer.contact_email,
            requested_delivery_date=ex.customer.target_delivery_date,
            language=ex.language,
            extraction=ex.model_dump(mode="json"),
            llm_model=extracted.model,
            llm_compliance_hash=extracted.compliance.compliance_hash,
        )
        s.add(quote)
        await s.flush()

        await self._trail(
            quote,
            actor_id,
            "rfq.received",
            {
                "rfq_id": str(rfq.id),
                "chars": len(raw_text),
                "text_sha256": hashlib.sha256(raw_text.encode()).hexdigest(),
                "customer_ref": customer_ref,
            },
        )
        await self._trail(
            quote,
            f"ai:{extracted.model}",
            "ai.extraction",
            self._extraction_event(extracted, customer_match),
        )

        matches: list[dict[str, Any]] = []
        for line in ex.line_items:
            await self._add_line(quote, line, margin, totals, matches)
        if ex.open_questions:
            totals.reasons.extend(f"Open question: {q}" for q in ex.open_questions)

        quote.material_cost = money(totals.material_cost)
        quote.labor_hours = totals.labor_hours.quantize(Decimal("0.01"))
        quote.labor_cost = money(totals.labor_cost)
        quote.total_cost = money(totals.material_cost + totals.labor_cost)
        quote.net_total = money(totals.net_total)
        quote.review_reasons = totals.reasons
        quote.status = QuoteStatus.NEEDS_REVIEW if totals.reasons else QuoteStatus.DRAFT
        rfq.status = RfqStatus.QUOTED

        await self._trail(quote, "system:matcher", "ai.matching", {"items": matches})
        await self._trail(
            quote,
            "system:costing",
            "quote.priced",
            {
                "currency": quote.currency,
                "margin_pct": str(margin),
                "material_cost": str(quote.material_cost),
                "labor_hours": str(quote.labor_hours),
                "labor_cost": str(quote.labor_cost),
                "total_cost": str(quote.total_cost),
                "net_total": str(quote.net_total),
            },
        )
        await self._trail(
            quote,
            actor_id,
            "quote.created",
            {
                "status": quote.status.value,
                "review_reasons": quote.review_reasons,
            },
        )
        await record_audit(
            s,
            actor_id=actor_id,
            action="quote.generated_from_rfq",
            entity_type="quote",
            entity_id=quote.id,
            ip_sha256=ip_sha256,
            context={
                "rfq_id": str(rfq.id),
                "status": quote.status.value,
                "items": len(ex.line_items),
                "llm_compliance_hash": extracted.compliance.compliance_hash,
            },
        )
        await s.flush()
        return quote

    # ----------------------------------------------------------------- helpers

    async def _trail(self, quote: Quote, actor: str, event: str, details: dict[str, Any]) -> None:
        self.session.add(
            QuoteAuditTrail(quote_id=quote.id, actor_id=actor[:128], event=event, details=details)
        )

    @staticmethod
    def _extraction_event(
        extracted: ExtractionResult, customer_match: dict[str, Any] | None
    ) -> dict[str, Any]:
        ex = extracted.extraction
        return {
            "model": extracted.model,
            "compliance_hash": extracted.compliance.compliance_hash,
            "language": ex.language,
            "line_items": len(ex.line_items),
            "components": sum(len(i.components) for i in ex.line_items),
            "customer_match": customer_match,
        }

    def _link(self, result: MatchResult) -> tuple[MatchResult, bool]:
        """Link the best candidate if it is at least a plausible suggestion."""
        linked = result.best is not None and result.confidence >= self.config.suggestion_floor
        return result, linked

    def _match_columns(self, result: MatchResult, linked: bool) -> dict[str, Any]:
        best = result.best if linked else None
        return {
            "material_id": best.material_id if best else None,
            "matnr": best.matnr if best else None,
            "material_type": best.material_type if best else None,
            "match_status": result.status,
            "match_confidence": Decimal(str(result.confidence)),
            "match_method": result.method,
            "match_candidates": [
                {**c.as_dict(), "flags": result.flags if c is result.best else []}
                for c in result.candidates
            ],
        }

    async def _match(
        self,
        *,
        description: str,
        search_text: str,
        kind: str,
        unit: str,
        material_number: str | None = None,
    ) -> tuple[MatchResult, bool]:
        result = await self.matcher.match(
            description=description,
            search_text=search_text,
            kind=kind,
            unit=unit,
            material_number=material_number,
        )
        return self._link(result)

    async def _add_line(
        self,
        quote: Quote,
        line: LineItem,
        margin: Decimal,
        totals: _Totals,
        matches: list[dict[str, Any]],
    ) -> None:
        qty = to_decimal(line.quantity)
        position = line.position * 10  # SAP-style item numbers 10, 20, ...
        custom = line.is_custom_made and line.kind == "finished_good"
        result, linked = await self._match(
            description=line.description,
            search_text=line.search_text,
            kind=line.kind,
            unit=line.unit,
            material_number=line.material_number,
        )
        matches.append(_match_summary(position, line.description, result, linked))

        item = QuoteItem(
            quote_id=quote.id,
            position=position,
            kind=QuoteItemKind(line.kind),
            description=line.description[:300],
            requested_description=line.description[:1000],
            specs=[sp.model_dump(mode="json") for sp in line.specs],
            quantity=qty,
            uom=line.unit,
        )
        if custom:
            # A made-to-order good has no SAP material yet; similar FERTs are kept for reference.
            item.sourcing = Sourcing.CUSTOM_BUILD
            item.match_status = MatchStatus.NOT_APPLICABLE
            item.match_candidates = [c.as_dict() for c in result.candidates]
            totals.reasons.append(
                f"Item {position}: AI-proposed BOM and labor for custom build must be confirmed; "
                "a new SAP material (FERT) is needed before ERP sync"
            )
        else:
            for k, v in self._match_columns(result, linked).items():
                setattr(item, k, v)
            item.sourcing = Sourcing.CATALOG if linked else Sourcing.MISSING_IN_CATALOG
            if result.needs_review:
                totals.reasons.append(_review_reason(position, line.description, result, linked))
        self.session.add(item)
        await self.session.flush()

        if custom:
            unit_cost = await self._add_children(quote, item, line, qty, totals, matches)
        elif linked and result.best is not None:
            unit_cost = material_unit_cost(result.best.standard_price, result.best.price_unit)
            if unit_cost is not None:
                totals.material_cost += unit_cost * qty
        else:
            unit_cost = None

        if unit_cost is None:
            totals.reasons.append(f"Item {position}: no price available")
            return
        priced = price_line(unit_cost, qty, margin)
        item.unit_cost = priced.unit_cost
        item.extended_cost = money(priced.unit_cost * qty)
        item.margin_pct = priced.margin_pct
        item.unit_margin = priced.unit_margin
        item.unit_price = priced.unit_price
        item.line_total = priced.line_total
        totals.net_total += priced.line_total

    async def _add_children(
        self,
        quote: Quote,
        parent: QuoteItem,
        line: LineItem,
        qty: Decimal,
        totals: _Totals,
        matches: list[dict[str, Any]],
    ) -> Decimal | None:
        """Components + labor below a custom finished good. Returns cost per finished unit."""
        cost_per_unit = Decimal(0)
        complete = True
        position = 0
        for comp in line.components:
            position += 1
            child, comp_cost = await self._component(
                quote, parent, comp, qty, position, totals, matches
            )
            self.session.add(child)
            if comp_cost is None:
                complete = False
            else:
                cost_per_unit += comp_cost
        for op in line.labor:
            position += 1
            per_unit = to_decimal(op.hours_per_unit, "0.01")
            hours = per_unit * qty
            rate = self.config.labor.rate(op.operation)
            extended = money(hours * rate)
            self.session.add(
                QuoteItem(
                    quote_id=quote.id,
                    parent_item_id=parent.id,
                    position=position,
                    kind=QuoteItemKind.LABOR,
                    description=f"{op.operation.replace('_', ' ').title()}"
                    + (f": {op.note}" if op.note else ""),
                    quantity=hours,
                    quantity_per_parent=per_unit,
                    uom="HUR",
                    match_status=MatchStatus.NOT_APPLICABLE,
                    sourcing=Sourcing.INTERNAL,
                    unit_cost=unit_amount(rate),
                    labor_hours=hours,
                    labor_rate=rate,
                    extended_cost=extended,
                )
            )
            totals.labor_hours += hours
            totals.labor_cost += extended
            cost_per_unit += per_unit * rate
        if not line.labor:
            totals.reasons.append(
                f"Item {parent.position}: no fabrication labor estimated for custom build"
            )
        return cost_per_unit if complete else None

    async def _component(
        self,
        quote: Quote,
        parent: QuoteItem,
        comp: BomComponent,
        parent_qty: Decimal,
        position: int,
        totals: _Totals,
        matches: list[dict[str, Any]],
    ) -> tuple[QuoteItem, Decimal | None]:
        per_unit = to_decimal(comp.quantity_per_unit)
        quantity = per_unit * parent_qty
        result, linked = await self._match(
            description=comp.description,
            search_text=comp.search_text,
            kind=comp.kind,
            unit=comp.unit,
        )
        label = f"{parent.position}.{position}"
        matches.append(_match_summary(label, comp.description, result, linked))
        child = QuoteItem(
            quote_id=quote.id,
            parent_item_id=parent.id,
            position=position,
            kind=QuoteItemKind(comp.kind),
            description=comp.description[:300],
            requested_description=comp.description[:1000],
            specs=[sp.model_dump(mode="json") for sp in comp.specs],
            quantity=quantity,
            quantity_per_parent=per_unit,
            uom=comp.unit,
            sourcing=Sourcing.CATALOG if linked else Sourcing.MISSING_IN_CATALOG,
            **self._match_columns(result, linked),
        )
        if result.needs_review:
            totals.reasons.append(_review_reason(label, comp.description, result, linked))
        unit_cost = (
            material_unit_cost(result.best.standard_price, result.best.price_unit)
            if linked and result.best is not None
            else None
        )
        if unit_cost is None:
            if linked:
                totals.reasons.append(
                    f"Component {label}: material {child.matnr} has no price in SAP"
                )
            return child, None
        child.unit_cost = unit_cost
        child.extended_cost = money(unit_cost * quantity)
        totals.material_cost += unit_cost * quantity
        return child, unit_cost * per_unit


def _match_summary(
    position: int | str, description: str, result: MatchResult, linked: bool
) -> dict[str, Any]:
    return {
        "position": str(position),
        "description": description[:120],
        "matnr": result.best.matnr if (linked and result.best) else None,
        "confidence": result.confidence,
        "status": result.status.value,
        "method": result.method,
        "flags": result.flags,
    }


def _review_reason(position: int | str, description: str, result: MatchResult, linked: bool) -> str:
    if not linked:
        return f"Item {position} '{description[:60]}': not found in SAP catalog (missing material)"
    assert result.best is not None
    return (
        f"Item {position} '{description[:60]}': match {result.best.matnr} "
        f"has confidence {result.confidence:.2f} (NEEDS_HUMAN_REVIEW)"
    )
