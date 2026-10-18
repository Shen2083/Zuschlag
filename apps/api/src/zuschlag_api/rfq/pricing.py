"""Deterministic costing. All money is Decimal; nothing here talks to the LLM."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
MILLI_CENT = Decimal("0.0001")
HUNDRED = Decimal(100)

DEFAULT_LABOR_RATES_EUR: dict[str, Decimal] = {
    "cutting": Decimal("85"),
    "bending": Decimal("85"),
    "welding": Decimal("92"),
    "machining": Decimal("95"),
    "assembly": Decimal("68"),
    "surface_treatment": Decimal("55"),
    "quality_inspection": Decimal("75"),
}


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def unit_amount(value: Decimal) -> Decimal:
    return value.quantize(MILLI_CENT, rounding=ROUND_HALF_UP)


def to_decimal(value: float | int | str | Decimal, places: str = "0.001") -> Decimal:
    """LLM numbers arrive as floats; go through str to avoid binary artefacts."""
    return Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def material_unit_cost(standard_price: Decimal | None, price_unit: int) -> Decimal | None:
    """SAP prices are per `price_unit` (PEINH) base units."""
    if standard_price is None:
        return None
    return unit_amount(standard_price / Decimal(max(price_unit, 1)))


@dataclass(frozen=True, slots=True)
class LaborRates:
    rates: Mapping[str, Decimal]
    default: Decimal = Decimal("80")

    def rate(self, operation: str) -> Decimal:
        return self.rates.get(operation, self.default)


@dataclass(frozen=True, slots=True)
class PricedLine:
    unit_cost: Decimal
    margin_pct: Decimal
    unit_margin: Decimal
    unit_price: Decimal
    line_total: Decimal


def price_line(unit_cost: Decimal, quantity: Decimal, margin_pct: Decimal) -> PricedLine:
    """Zuschlagskalkulation: unit price = unit cost + margin (Zuschlag) on cost."""
    unit_margin = unit_amount(unit_cost * margin_pct / HUNDRED)
    unit_price = unit_amount(unit_cost + unit_margin)
    return PricedLine(
        unit_cost=unit_amount(unit_cost),
        margin_pct=margin_pct,
        unit_margin=unit_margin,
        unit_price=unit_price,
        line_total=money(unit_price * quantity),
    )
