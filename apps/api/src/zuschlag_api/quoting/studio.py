"""Human-in-the-loop changes from the Quote Studio: inline BOM edits and approval.

Every change is repriced with the same engine as POST /calculate, written to
the append-only `quote_audit_trail` with before/after values. An approved
quote is frozen: editing it opens the next revision (v1 -> v2), which has to be
approved again.
"""

from __future__ import annotations

import enum
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zuschlag_api.audit.service import record_audit
from zuschlag_api.models import (
    MatchStatus,
    Material,
    Quote,
    QuoteAuditTrail,
    QuoteItem,
    QuoteItemKind,
    QuoteStatus,
    Sourcing,
)
from zuschlag_api.quoting.calculation import MAX_ZUSCHLAG_PCT, VatRate, calculate
from zuschlag_api.quoting.service import (
    QuoteLockedError,
    apply_calculation,
    line_inputs,
    load_quote,
    open_revision,
    quote_snapshot,
    revision_label,
    snapshot_sha256,
)
from zuschlag_api.rfq.pricing import material_unit_cost, money, unit_amount

UOM = re.compile(r"^[A-Z0-9]{2,3}$")
QTY = Decimal("0.001")


class ItemNotFoundError(LookupError):
    pass


class ItemEditError(ValueError):
    """The requested change is not valid for this item."""


class CatalogWarning(enum.StrEnum):
    MISSING_IN_CATALOG = "missing_in_catalog"  # no SAP material matched
    NEEDS_FERT = "needs_fert"  # custom build without its own SAP material yet
    DELETED = "deleted"  # linked MATNR no longer in the mirrored MATMAS
    INACTIVE = "inactive"  # material flagged for deletion / blocked in SAP
    NO_PRICE = "no_price"  # MATMAS has no MBEW valuation price


def catalog_warnings(
    items: list[QuoteItem], materials: dict[uuid.UUID, Material]
) -> dict[uuid.UUID, CatalogWarning]:
    out: dict[uuid.UUID, CatalogWarning] = {}
    for item in items:
        if item.kind is QuoteItemKind.LABOR or item.sourcing is Sourcing.INTERNAL:
            continue
        if item.material_id is not None:
            material = materials.get(item.material_id)
            if material is None:
                out[item.id] = CatalogWarning.DELETED
            elif not material.is_active:
                out[item.id] = CatalogWarning.INACTIVE
            elif material.standard_price is None and item.sourcing is not Sourcing.CUSTOM_BUILD:
                out[item.id] = CatalogWarning.NO_PRICE
        elif item.sourcing is Sourcing.CUSTOM_BUILD:
            out[item.id] = CatalogWarning.NEEDS_FERT
        elif item.sourcing is Sourcing.MISSING_IN_CATALOG or item.matnr is None:
            out[item.id] = CatalogWarning.MISSING_IN_CATALOG
    return out


async def linked_materials(
    session: AsyncSession, items: list[QuoteItem]
) -> dict[uuid.UUID, Material]:
    ids = {i.material_id for i in items if i.material_id is not None}
    if not ids:
        return {}
    rows = await session.scalars(select(Material).where(Material.id.in_(ids)))
    return {m.id: m for m in rows}


def approve_blockers(quote: Quote, items: list[QuoteItem]) -> list[str]:
    """Hard requirements before an estimator may approve the quote."""
    reasons: list[str] = []
    if quote.status is QuoteStatus.SYNCED:
        reasons.append("quote is already synced to SAP")
    if quote.calculated_at is None or quote.payment_terms is None:
        reasons.append("quote has not been calculated (Zuschlag, VAT and payment terms)")
    top_level = [i for i in items if i.parent_item_id is None]
    if not top_level:
        reasons.append("quote has no items")
    for item in items:
        label = _label(item, items)
        if item.match_status is MatchStatus.NEEDS_HUMAN_REVIEW:
            reasons.append(f"Item {label}: SAP match needs human review")
    for item in top_level:
        if item.unit_price is None:
            reasons.append(f"Item {item.position:05d}: not priced")
    return reasons


def _label(item: QuoteItem, items: list[QuoteItem]) -> str:
    if item.parent_item_id is None:
        return f"{item.position:05d}"
    parent = next((i for i in items if i.id == item.parent_item_id), None)
    return f"{parent.position if parent else '?'}.{item.position}"


# --------------------------------------------------------------------------- #
# Inline edit
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ItemPatch:
    """Only the fields present in `fields` are changed."""

    fields: frozenset[str]
    quantity: Decimal | None = None
    matnr: str | None = None
    description: str | None = None
    uom: str | None = None
    unit_cost: Decimal | None = None


def _snapshot(item: QuoteItem) -> dict[str, Any]:
    return {
        "quantity": str(item.quantity),
        "matnr": item.matnr,
        "description": item.description,
        "uom": item.uom,
        "unit_cost": None if item.unit_cost is None else str(item.unit_cost),
        "match_status": item.match_status.value,
    }


def _rollup(items: list[QuoteItem]) -> None:
    """Recompute line costs bottom-up: components -> custom-build parent."""
    children: dict[uuid.UUID, list[QuoteItem]] = defaultdict(list)
    for item in items:
        if item.parent_item_id is not None:
            children[item.parent_item_id].append(item)
    for item in items:
        if item.parent_item_id is None:
            continue
        if item.kind is QuoteItemKind.LABOR:
            item.labor_hours = item.quantity.quantize(Decimal("0.01"))
        item.extended_cost = (
            None if item.unit_cost is None else money(item.unit_cost * item.quantity)
        )
    for item in items:
        kids = children.get(item.id)
        if kids:
            if all(k.unit_cost is not None and k.quantity_per_parent is not None for k in kids):
                per_unit = sum(
                    (k.unit_cost * k.quantity_per_parent for k in kids),  # type: ignore[operator]
                    Decimal(0),
                )
                item.unit_cost = unit_amount(per_unit)
            else:
                item.unit_cost = None
        if item.parent_item_id is None:
            item.extended_cost = (
                None if item.unit_cost is None else money(item.unit_cost * item.quantity)
            )


async def _assign_material(
    session: AsyncSession, item: QuoteItem, matnr: str | None, *, has_children: bool
) -> None:
    if item.kind is QuoteItemKind.LABOR:
        raise ItemEditError("labor operations have no SAP material")
    if matnr is None:
        item.material_id = None
        item.matnr = None
        item.material_type = None
        item.match_status = (
            MatchStatus.NEEDS_HUMAN_REVIEW if not has_children else MatchStatus.NOT_APPLICABLE
        )
        item.match_method = "manual"
        item.match_confidence = None
        if not has_children:
            item.sourcing = Sourcing.MISSING_IN_CATALOG
            item.unit_cost = None
        return
    key = matnr.strip()
    material = await session.scalar(select(Material).where(Material.matnr == key))
    if material is None and key.isdigit():
        material = await session.scalar(select(Material).where(Material.matnr == key.zfill(18)))
    if material is None:
        raise ItemEditError(f"material {key} not found in the SAP material master (MATMAS)")
    if not material.is_active:
        raise ItemEditError(f"material {material.matnr} is inactive in SAP")
    item.material_id = material.id
    item.matnr = material.matnr
    item.material_type = material.material_type
    item.match_status = MatchStatus.MATCHED
    item.match_method = "manual"
    item.match_confidence = Decimal("1.00")
    if material.description:
        item.description = material.description[:300]
    if not has_children:
        # A custom build keeps its component-based cost; a catalog item takes the SAP price.
        item.sourcing = Sourcing.CATALOG
        item.unit_cost = material_unit_cost(material.standard_price, material.price_unit)


async def edit_item(
    session: AsyncSession,
    quote_id: uuid.UUID,
    item_id: uuid.UUID,
    patch: ItemPatch,
    *,
    actor_id: str,
    ip_sha256: str | None,
) -> Quote:
    quote, items = await load_quote(session, quote_id)
    if quote.status is QuoteStatus.SYNCED:
        raise QuoteLockedError(f"quote {quote.quote_number} is already synced to SAP")
    item = next((i for i in items if i.id == item_id), None)
    if item is None:
        raise ItemNotFoundError(str(item_id))
    kids = [i for i in items if i.parent_item_id == item.id]
    parent = next((i for i in items if i.id == item.parent_item_id), None)
    before = _snapshot(item)
    reopened = quote.status is QuoteStatus.APPROVED
    if reopened:
        await open_revision(session, quote, items, actor_id=actor_id, reason="item.edited")

    if "matnr" in patch.fields:
        await _assign_material(session, item, patch.matnr or None, has_children=bool(kids))
    if "description" in patch.fields:
        text = (patch.description or "").strip()
        if not text:
            raise ItemEditError("description must not be empty")
        item.description = text[:300]
    if "uom" in patch.fields:
        uom = (patch.uom or "").strip().upper()
        if not UOM.match(uom):
            raise ItemEditError("unit must be an ISO unit code such as PCE, KGM or HUR")
        item.uom = uom
    if "unit_cost" in patch.fields:
        if kids:
            raise ItemEditError("the cost of a custom build is rolled up from its components")
        if patch.unit_cost is not None and patch.unit_cost < 0:
            raise ItemEditError("unit cost must not be negative")
        item.unit_cost = None if patch.unit_cost is None else unit_amount(patch.unit_cost)
        if item.kind is QuoteItemKind.LABOR and patch.unit_cost is not None:
            item.labor_rate = patch.unit_cost.quantize(Decimal("0.01"))
    if "quantity" in patch.fields:
        qty = patch.quantity
        if qty is None or qty <= 0:
            raise ItemEditError("quantity must be greater than zero")
        qty = qty.quantize(QTY)
        item.quantity = qty
        if parent is not None:
            item.quantity_per_parent = (qty / parent.quantity).quantize(QTY)
        for kid in kids:  # components scale with the finished good
            if kid.quantity_per_parent is not None:
                kid.quantity = (kid.quantity_per_parent * qty).quantize(QTY)

    _rollup(items)
    pct = min(quote.margin_pct, MAX_ZUSCHLAG_PCT)
    vat = VatRate.from_percent(quote.vat_rate) if quote.vat_rate is not None else VatRate.STANDARD
    calc = calculate(line_inputs(items), zuschlag_pct=pct, vat_rate=vat)
    apply_calculation(quote, items, calc)
    quote.labor_hours = sum(
        (i.labor_hours or Decimal(0) for i in items if i.kind is QuoteItemKind.LABOR), Decimal(0)
    ).quantize(Decimal("0.01"))

    after = _snapshot(item)
    session.add(
        QuoteAuditTrail(
            quote_id=quote.id,
            actor_id=actor_id[:128],
            event="item.edited",
            details={
                "item_id": str(item.id),
                "revision": revision_label(quote.revision),
                "position": _label(item, items),
                "changed": sorted(k for k in after if after[k] != before[k]),
                "before": before,
                "after": after,
                "net_total": str(quote.net_total),
                "approval_revoked": reopened,
            },
        )
    )
    await record_audit(
        session,
        actor_id=actor_id,
        action="quote.item.edited",
        entity_type="quote",
        entity_id=quote.id,
        ip_sha256=ip_sha256,
        context={"item_id": str(item.id), "fields": sorted(patch.fields)},
    )
    await session.flush()
    return quote


# --------------------------------------------------------------------------- #
# Approval
# --------------------------------------------------------------------------- #


class ApprovalBlockedError(RuntimeError):
    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


async def approve_quote(
    session: AsyncSession,
    quote_id: uuid.UUID,
    *,
    actor_id: str,
    ip_sha256: str | None,
    comment: str | None = None,
) -> Quote:
    quote, items = await load_quote(session, quote_id)
    if quote.status is QuoteStatus.SYNCED:
        raise QuoteLockedError(f"quote {quote.quote_number} is already synced to SAP")
    if quote.status is QuoteStatus.APPROVED:
        return quote
    reasons = approve_blockers(quote, items)
    if reasons:
        raise ApprovalBlockedError(reasons)
    previous = quote.status
    quote.status = QuoteStatus.APPROVED
    frozen = quote_snapshot(quote, items)
    session.add(
        QuoteAuditTrail(
            quote_id=quote.id,
            actor_id=actor_id[:128],
            event="quote.approved",
            details={
                "revision": revision_label(quote.revision),
                # What this approval froze; a later revision must reproduce this hash.
                "snapshot": frozen,
                "snapshot_sha256": snapshot_sha256(frozen),
                "previous_status": previous.value,
                # The AI review notes the approver has seen and accepted.
                "acknowledged_review_reasons": quote.review_reasons,
                "net_total": str(quote.net_total),
                "gross_total": str(quote.gross_total),
                "margin_pct": str(quote.margin_pct),
                "payment_terms": quote.payment_terms,
                "comment": (comment or "")[:500] or None,
                "approved_at": datetime.now(UTC).isoformat(),
            },
        )
    )
    await record_audit(
        session,
        actor_id=actor_id,
        action="quote.approved",
        entity_type="quote",
        entity_id=quote.id,
        ip_sha256=ip_sha256,
        context={"net_total": str(quote.net_total), "currency": quote.currency},
    )
    await session.flush()
    return quote
