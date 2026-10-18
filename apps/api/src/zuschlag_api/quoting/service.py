"""Recalculate a stored quote (POST /quotes/{id}/calculate) and manage revisions.

GoBD: an approved quote is frozen (enforced by database triggers, migration
0005). A later change does not overwrite it: it opens the next revision, and
the frozen predecessor is preserved as a snapshot with its SHA-256 in the
append-only `quote_audit_trail` (`quote.revision.created`).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

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


def revision_label(revision: int) -> str:
    return f"v{revision}"


def _str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def quote_snapshot(quote: Quote, items: list[QuoteItem]) -> dict[str, Any]:
    """Everything a revision commits to: prices, quantities, materials, terms."""
    return {
        "quote_number": quote.quote_number,
        "revision": revision_label(quote.revision),
        "currency": quote.currency,
        "customer_id": None if quote.customer_id is None else str(quote.customer_id),
        "margin_pct": str(quote.margin_pct),
        "material_cost": str(quote.material_cost),
        "labor_cost": str(quote.labor_cost),
        "total_cost": str(quote.total_cost),
        "net_total": str(quote.net_total),
        "vat_rate": _str(quote.vat_rate),
        "vat_amount": str(quote.vat_amount),
        "gross_total": str(quote.gross_total),
        "payment_terms": quote.payment_terms,
        "items": [
            {
                "id": str(i.id),
                "parent_item_id": None if i.parent_item_id is None else str(i.parent_item_id),
                "position": i.position,
                "kind": i.kind.value,
                "matnr": i.matnr,
                "description": i.description,
                "quantity": str(i.quantity),
                "uom": i.uom,
                "unit_cost": _str(i.unit_cost),
                "unit_price": _str(i.unit_price),
                "line_total": _str(i.line_total),
            }
            for i in items
        ],
    }


def snapshot_sha256(snapshot: dict[str, Any]) -> str:
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def open_revision(
    session: AsyncSession, quote: Quote, items: list[QuoteItem], *, actor_id: str, reason: str
) -> None:
    """Leave the frozen, approved revision n for an editable revision n + 1."""
    frozen = quote_snapshot(quote, items)
    quote.revision += 1
    quote.status = QuoteStatus.DRAFT
    session.add(
        QuoteAuditTrail(
            quote_id=quote.id,
            actor_id=actor_id[:128],
            event="quote.revision.created",
            details={
                "revision": revision_label(quote.revision),
                "supersedes": frozen["revision"],
                "reason": reason,
                "frozen_snapshot": frozen,
                "frozen_snapshot_sha256": snapshot_sha256(frozen),
            },
        )
    )
    # The quote row must leave `approved` before any of its items change (trigger order).
    await session.flush()


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

    if quote.status is QuoteStatus.APPROVED:
        unchanged = (
            quote.margin_pct == calc.zuschlag_pct
            and quote.vat_rate == calc.vat_rate.value
            and quote.payment_terms == terms.terms.zterm
            and quote.net_total == calc.net_amount
            and quote.gross_total == calc.gross_amount
        )
        if unchanged:  # nothing to change: the approved revision stays as it is
            return Recalculation(quote, calc, terms)
        await open_revision(session, quote, items, actor_id=actor_id, reason="quote.calculated")

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
                "revision": revision_label(quote.revision),
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
