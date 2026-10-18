from __future__ import annotations

from decimal import Decimal

from zuschlag_api.rfq.pricing import LaborRates, material_unit_cost, money, price_line


def test_sap_price_unit_is_respected() -> None:
    assert material_unit_cost(Decimal("389.00"), 10) == Decimal("38.9000")  # PEINH = 10
    assert material_unit_cost(Decimal("148.50"), 1) == Decimal("148.5000")
    assert material_unit_cost(None, 1) is None


def test_zuschlag_on_cost() -> None:
    line = price_line(Decimal("2311.50"), Decimal("15"), Decimal("22"))
    assert line.unit_margin == Decimal("508.5300")
    assert line.unit_price == Decimal("2820.0300")
    assert line.line_total == Decimal("42300.45")


def test_rounding_is_commercial() -> None:
    assert money(Decimal("0.125")) == Decimal("0.13")  # half-up, not banker's rounding
    assert money(Decimal("0.135")) == Decimal("0.14")


def test_labor_rates_fall_back_to_default() -> None:
    rates = LaborRates({"welding": Decimal("92")}, default=Decimal("80"))
    assert rates.rate("welding") == Decimal("92")
    assert rates.rate("machining") == Decimal("80")
