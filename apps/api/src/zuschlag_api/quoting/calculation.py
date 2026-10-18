"""German quotation arithmetic (Zuschlagskalkulation).

    Materialkosten + Fertigungskosten (Lohn)   = Herstellkosten (factory cost)
    Herstellkosten  x Zuschlag %               = Zuschlag
    Herstellkosten  + Zuschlag                 = Nettobetrag
    Nettobetrag     x MwSt 19 % | 7 %          = Mehrwertsteuer
    Nettobetrag     + Mehrwertsteuer           = Bruttobetrag

The Zuschlag is applied per unit (so unit prices are what SAP and the customer
see), rounded commercially to 4 decimals per unit and to cents per line. VAT is
computed once on the net total, as on a German invoice.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from zuschlag_api.rfq.pricing import HUNDRED, money, price_line

MAX_ZUSCHLAG_PCT = Decimal(100)


class VatRate(enum.Enum):
    """§ 12 UStG: 19 % standard rate, 7 % reduced rate."""

    STANDARD = Decimal("19")
    REDUCED = Decimal("7")

    @classmethod
    def from_percent(cls, value: Decimal | int | str) -> VatRate:
        pct = Decimal(str(value))
        for rate in cls:
            if rate.value == pct:
                return rate
        raise ValueError(f"VAT rate must be 19 or 7 percent, got {value}")


@dataclass(frozen=True, slots=True)
class LineInput:
    item_id: uuid.UUID
    position: int
    quantity: Decimal
    unit_cost: Decimal | None  # Herstellkosten per unit; None = not priceable yet
    material_cost: Decimal  # line total, cents
    labor_cost: Decimal  # line total, cents


@dataclass(frozen=True, slots=True)
class LineResult:
    item_id: uuid.UUID
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


@dataclass(frozen=True, slots=True)
class Calculation:
    zuschlag_pct: Decimal
    vat_rate: VatRate
    lines: list[LineResult]
    missing_price_positions: list[int] = field(default_factory=list)

    @property
    def material_cost(self) -> Decimal:
        return money(sum((line.material_cost for line in self.lines), Decimal(0)))

    @property
    def labor_cost(self) -> Decimal:
        return money(sum((line.labor_cost for line in self.lines), Decimal(0)))

    @property
    def factory_cost(self) -> Decimal:
        """Herstellkosten."""
        return money(self.material_cost + self.labor_cost)

    @property
    def net_amount(self) -> Decimal:
        """Nettobetrag."""
        return money(sum((line.net_amount for line in self.lines), Decimal(0)))

    @property
    def zuschlag_amount(self) -> Decimal:
        return money(self.net_amount - self.factory_cost)

    @property
    def vat_amount(self) -> Decimal:
        """Mehrwertsteuer on the net total."""
        return money(self.net_amount * self.vat_rate.value / HUNDRED)

    @property
    def gross_amount(self) -> Decimal:
        """Bruttobetrag."""
        return money(self.net_amount + self.vat_amount)

    @property
    def complete(self) -> bool:
        return not self.missing_price_positions


def calculate(
    lines: Sequence[LineInput], *, zuschlag_pct: Decimal, vat_rate: VatRate
) -> Calculation:
    if not Decimal(0) <= zuschlag_pct <= MAX_ZUSCHLAG_PCT:
        raise ValueError(f"Zuschlag must be between 0 and 100 percent, got {zuschlag_pct}")
    results: list[LineResult] = []
    missing: list[int] = []
    for line in sorted(lines, key=lambda x: x.position):
        if line.unit_cost is None:
            missing.append(line.position)
            continue
        priced = price_line(line.unit_cost, line.quantity, zuschlag_pct)
        results.append(
            LineResult(
                item_id=line.item_id,
                position=line.position,
                quantity=line.quantity,
                unit_cost=priced.unit_cost,
                material_cost=money(line.material_cost),
                labor_cost=money(line.labor_cost),
                factory_cost=money(line.material_cost + line.labor_cost),
                zuschlag_pct=zuschlag_pct,
                unit_zuschlag=priced.unit_margin,
                unit_price=priced.unit_price,
                net_amount=priced.line_total,
            )
        )
    return Calculation(zuschlag_pct, vat_rate, results, missing)
