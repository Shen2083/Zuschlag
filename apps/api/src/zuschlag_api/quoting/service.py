"""Recalculate a stored quote (POST /quotes/{id}/calculate)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zuschlag_api.models import (
    CustomerSalesArea,
    Quote,
    QuoteAuditTrail,
    QuoteItem,
    QuoteItemKind,
    QuoteStatus,
)
from zuschlag_api.quoting.calculation import Calculation, LineInput, VatRate, calculate
from zuschlag_api.quoting.payment_terms import TermsDecision, resolve_payment_terms
from zuschlag_api.rfq.pricing import money


class QuoteNotFoundError(LookupError):
    pass


class QuoteLockedError(RuntimeError):
    """The quote was already synced to SAP and can no longer change."""


@dataclass(frozen=True, slots=True)
class Recalculation:
    quote: Quote
    calculation: Calculation
    terms: TermsDecision


async def load_quote(session: AsyncSession, quote_id: uuid.UUID) -> tuple[Quote, list[QuoteItem]]:
    quote = await session.scalar(select(Quote).where(Quote.id == quote_id))
    if quote is None:
        raise QuoteNotFoundError(str(quote_id))
    items = list(
        await session.scalars(
            select(QuoteItem)
            .where(QuoteItem.quote_id == quote_id)
            .order_by(QuoteItem.parent_item_id.nulls_first(), QuoteItem.position)
        )
    )
    return quote, items


async def agreed_payment_terms(session: AsyncSession, customer_id: uuid.UUID | None) -> list[str]:
    """The customer's ZTERMs from SAP (KNVV), in sales-area order."""
    if customer_id is None:
        return []
    rows = await session.scalars(
        select(CustomerSalesArea.payment_terms)
        .where(
            CustomerSalesArea.customer_id == customer_id,
            CustomerSalesArea.is_active,
            CustomerSalesArea.payment_terms.is_not(None),
        )
        .order_by(CustomerSalesArea.sales_org, CustomerSalesArea.distribution_channel)
    )
    return [r for r in rows if r]


def line_inputs(items: list[QuoteItem]) -> list[LineInput]:
    """Top-level lines with their Herstellkosten split into material and labor."""
    children: dict[uuid.UUID, list[QuoteItem]] = defaultdict(list)
    for item in items:
        if item.parent_item_id is not None:
            children[item.parent_item_id].append(item)
    inputs: list[LineInput] = []
    for item in items:
        if item.parent_item_id is not None:
            continue
        kids = children.get(item.id, [])
        if kids:
            labor = sum(
                (k.extended_cost or Decimal(0) for k in kids if k.kind is QuoteItemKind.LABOR),
                Decimal(0),
            )
            material = sum(
                (k.extended_cost or Decimal(0) for k in kids if k.kind is not QuoteItemKind.LABOR),
                Decimal(0),
            )
        elif item.kind is QuoteItemKind.LABOR:
            labor = money((item.unit_cost or Decimal(0)) * item.quantity)
            material = Decimal(0)
        else:
            labor = Decimal(0)
            material = money((item.unit_cost or Decimal(0)) * item.quantity)
        inputs.append(
            LineInput(
                item_id=item.id,
                position=item.position,
                quantity=item.quantity,
                unit_cost=item.unit_cost,
                material_cost=material,
                labor_cost=labor,
            )
        )
    return inputs


def apply_calculation(quote: Quote, items: list[QuoteItem], calc: Calculation) -> None:
    """Write line prices and quote totals. Unpriced top-level lines lose stale prices."""
    by_id = {line.item_id: line for line in calc.lines}
    for item in items:
        if item.parent_item_id is not None:
            continue
        line = by_id.get(item.id)
        item.margin_pct = line.zuschlag_pct if line else None
        item.unit_margin = line.unit_zuschlag if line else None
        item.unit_price = line.unit_price if line else None
        item.line_total = line.net_amount if line else None

    quote.margin_pct = calc.zuschlag_pct
    quote.material_cost = calc.material_cost
    quote.labor_cost = calc.labor_cost
    quote.total_cost = calc.factory_cost
    quote.net_total = calc.net_amount
    quote.vat_rate = calc.vat_rate.value
    quote.vat_amount = calc.vat_amount
    quote.gross_total = calc.gross_amount


async def recalculate_quote(
    session: AsyncSession,
    quote_id: uuid.UUID,
    *,
    zuschlag_pct: Decimal,
    vat_rate: VatRate,
    payment_terms: str | None,
    allow_terms_deviation: bool,
    default_payment_terms: str,
    payment_terms_catalog: Mapping[str, int],
    actor_id: str,
) -> Recalculation:
    quote, items = await load_quote(session, quote_id)
    if quote.status is QuoteStatus.SYNCED:
        raise QuoteLockedError(f"quote {quote.quote_number} is already synced to SAP")

    terms = resolve_payment_terms(
        payment_terms,
        agreed=await agreed_payment_terms(session, quote.customer_id),
        default=default_payment_terms,
        catalog=payment_terms_catalog,
        allow_deviation=allow_terms_deviation,
    )
    calc = calculate(line_inputs(items), zuschlag_pct=zuschlag_pct, vat_rate=vat_rate)

    before = {
        "margin_pct": str(quote.margin_pct),
        "net_total": str(quote.net_total),
        "gross_total": str(quote.gross_total),
        "payment_terms": quote.payment_terms,
    }
    apply_calculation(quote, items, calc)
    quote.payment_terms = terms.terms.zterm
    quote.calculated_at = datetime.now(UTC)

    session.add(
        QuoteAuditTrail(
            quote_id=quote.id,
            actor_id=actor_id[:128],
            event="quote.calculated",
            details={
                "before": before,
                "after": {
                    "margin_pct": str(calc.zuschlag_pct),
                    "factory_cost": str(calc.factory_cost),
                    "net_total": str(calc.net_amount),
                    "vat_rate": str(calc.vat_rate.value),
                    "vat_amount": str(calc.vat_amount),
                    "gross_total": str(calc.gross_amount),
                    "payment_terms": terms.terms.zterm,
                },
                "payment_terms_deviation": terms.deviation,
                "agreed_payment_terms": list(terms.agreed),
                "missing_price_positions": calc.missing_price_positions,
            },
        )
    )
    await session.flush()
    return Recalculation(quote, calc, terms)
