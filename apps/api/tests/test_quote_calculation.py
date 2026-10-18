"""Zuschlagskalkulation and payment terms (pure functions, no database)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from zuschlag_api.quoting.calculation import LineInput, VatRate, calculate
from zuschlag_api.quoting.payment_terms import (
    PaymentTermsError,
    parse_payment_terms,
    resolve_payment_terms,
)

CASTORS = LineInput(
    uuid.uuid4(),
    10,
    Decimal(40),
    Decimal("38.90"),
    material_cost=Decimal("1556.00"),
    labor_cost=Decimal(0),
)
RACKS = LineInput(
    uuid.uuid4(),
    20,
    Decimal(15),
    Decimal("2311.50"),
    material_cost=Decimal("22215.00"),
    labor_cost=Decimal("12457.50"),
)


def test_herstellkosten_zuschlag_netto_mwst_brutto_19() -> None:
    calc = calculate([RACKS, CASTORS], zuschlag_pct=Decimal(22), vat_rate=VatRate.STANDARD)
    assert [line.position for line in calc.lines] == [10, 20]  # sorted by position
    assert calc.material_cost == Decimal("23771.00")
    assert calc.labor_cost == Decimal("12457.50")
    assert calc.factory_cost == Decimal("36228.50")  # Herstellkosten
    castors, racks = calc.lines
    assert (castors.unit_price, castors.net_amount) == (Decimal("47.4580"), Decimal("1898.32"))
    assert (racks.unit_price, racks.net_amount) == (Decimal("2820.0300"), Decimal("42300.45"))
    assert calc.net_amount == Decimal("44198.77")  # Nettobetrag
    assert calc.zuschlag_amount == Decimal("7970.27")
    assert calc.vat_amount == Decimal("8397.77")  # 19 % MwSt
    assert calc.gross_amount == Decimal("52596.54")  # Bruttobetrag
    assert calc.complete


def test_reduced_vat_rate_7() -> None:
    calc = calculate([RACKS, CASTORS], zuschlag_pct=Decimal(22), vat_rate=VatRate.REDUCED)
    assert (calc.vat_amount, calc.gross_amount) == (Decimal("3093.91"), Decimal("47292.68"))


@pytest.mark.parametrize(
    ("pct", "net"), [(Decimal(0), Decimal("1556.00")), (Decimal(100), Decimal("3112.00"))]
)
def test_zuschlag_bounds(pct: Decimal, net: Decimal) -> None:
    assert calculate([CASTORS], zuschlag_pct=pct, vat_rate=VatRate.STANDARD).net_amount == net


@pytest.mark.parametrize("pct", [Decimal("-0.01"), Decimal("100.01")])
def test_zuschlag_outside_0_to_100_rejected(pct: Decimal) -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        calculate([CASTORS], zuschlag_pct=pct, vat_rate=VatRate.STANDARD)


def test_unpriced_lines_are_reported_not_guessed() -> None:
    unpriced = LineInput(uuid.uuid4(), 30, Decimal(5), None, Decimal(0), Decimal(0))
    calc = calculate([CASTORS, unpriced], zuschlag_pct=Decimal(10), vat_rate=VatRate.STANDARD)
    assert calc.missing_price_positions == [30]
    assert not calc.complete
    assert [line.position for line in calc.lines] == [10]


def test_only_german_vat_rates() -> None:
    assert VatRate.from_percent(19) is VatRate.STANDARD
    assert VatRate.from_percent("7") is VatRate.REDUCED
    with pytest.raises(ValueError, match="19 or 7"):
        VatRate.from_percent(16)


# --- payment terms ------------------------------------------------------------------


@pytest.mark.parametrize(("zterm", "days"), [("NT30", 30), ("nt14", 14), ("NT0", 0), ("0001", 0)])
def test_parse_known_terms(zterm: str, days: int) -> None:
    terms = parse_payment_terms(zterm, {"0001": 0})
    assert terms.net_days == days
    assert terms.zterm == zterm.upper()


def test_term_descriptions() -> None:
    assert parse_payment_terms("NT30").description_de == "30 Tage netto"
    assert parse_payment_terms("NT30").description_en == "net 30 days"


@pytest.mark.parametrize("zterm", ["ZB01", "NT1234", "", "NETTO30"])
def test_unknown_or_malformed_terms_rejected(zterm: str) -> None:
    with pytest.raises(PaymentTermsError):
        parse_payment_terms(zterm)


def test_defaults_to_customer_agreed_terms() -> None:
    d = resolve_payment_terms(None, agreed=["NT30", "NT60"], default="NT14")
    assert (d.terms.zterm, d.deviation, d.agreed) == ("NT30", False, ("NT30", "NT60"))


def test_falls_back_to_default_without_customer_terms() -> None:
    assert resolve_payment_terms(None, agreed=[], default="NT14").terms.zterm == "NT14"


def test_any_agreed_sales_area_term_is_accepted() -> None:
    assert not resolve_payment_terms("nt60", agreed=["NT30", "NT60"], default="NT30").deviation


def test_deviation_from_agreed_terms_needs_explicit_override() -> None:
    with pytest.raises(PaymentTermsError, match="deviate from the customer's agreed terms NT30"):
        resolve_payment_terms("NT90", agreed=["NT30"], default="NT30")
    d = resolve_payment_terms("NT90", agreed=["NT30"], default="NT30", allow_deviation=True)
    assert (d.terms.net_days, d.deviation) == (90, True)
