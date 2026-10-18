from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from zuschlag_api.models import MatchStatus, Quote, QuoteItem, QuoteItemKind, Sourcing
from zuschlag_api.sap.builder import IdocBuildError, SapPartnerProfile, build_quotation_idoc
from zuschlag_api.sap.orders05 import Orders05Quotation, sap_decimal

SCHEMA_DIR = Path(__file__).resolve().parents[3] / "packages" / "sap-schema"
SCHEMA = json.loads((SCHEMA_DIR / "schemas" / "orders05-quotation.schema.json").read_text())
EXAMPLE = json.loads((SCHEMA_DIR / "examples" / "orders05-quotation.example.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA)

PROFILE = SapPartnerProfile(
    client="100",
    sales_org="1000",
    distribution_channel="10",
    division="00",
    sender_port="ZUSCHLAG",
    sender_partner="ZUSCHLAG",
    receiver_port="SAPS4H",
    receiver_partner="S4HCLNT100",
)
CASTER_ID = uuid.uuid4()


def _quote(**overrides: Any) -> Quote:
    quote = Quote(
        quote_number="AN-2026-1187", currency="EUR", margin_pct=Decimal("22.00"), **overrides
    )
    quote.items = [
        QuoteItem(
            position=10,
            kind=QuoteItemKind.PURCHASED_PART,
            match_status=MatchStatus.MATCHED,
            sourcing=Sourcing.CATALOG,
            material_id=CASTER_ID,
            description="Heavy-duty swivel caster Ø125 mm, 150 kg, with brake",
            quantity=Decimal("60"),
            uom="PCE",
            unit_price=Decimal("38.9"),
        ),
        QuoteItem(
            position=20,
            kind=QuoteItemKind.LABOR,
            match_status=MatchStatus.NOT_APPLICABLE,
            sourcing=Sourcing.INTERNAL,
            description="TIG welding, stainless frame",
            quantity=Decimal("37.5"),
            uom="HUR",
            unit_price=Decimal("92"),
        ),
    ]
    return quote


def _build() -> Orders05Quotation:
    return build_quotation_idoc(
        _quote(),
        profile=PROFILE,
        sold_to="300184",
        created_at=datetime(2026, 10, 5, 9, 14, tzinfo=UTC),
        matnr_by_material_id={CASTER_ID: "PT-CAS-125HD"},
        customer_ref="REQ-2026-0412",
    )


def test_built_idoc_matches_shared_json_schema() -> None:
    errors = sorted(VALIDATOR.iter_errors(_build().to_idoc_json()), key=str)
    assert not errors, [e.message for e in errors]


def test_built_idoc_contents() -> None:
    idoc = _build().to_idoc_json()
    assert idoc["EDI_DC40"]["CREDAT"] == "20261005"
    assert {"QUALF": "012", "ORGID": "AG"} in idoc["E1EDK14"]
    labor = idoc["E1EDP01"][1]
    assert labor["MENGE"] == "37.5"
    assert labor["E1EDP19"][0]["IDTNR"] == "SRV-LABOR"
    assert labor["E1EDP05"] == [
        {"KSCHL": "PR00", "BETRG": "92.0000"},
        {"ALCKZ": "+", "KSCHL": "ZZUS", "KPERC": "22.000"},
    ]


def test_shared_example_parses_with_python_models() -> None:
    assert VALIDATOR.is_valid(EXAMPLE)
    assert Orders05Quotation.model_validate(EXAMPLE).to_idoc_json() == EXAMPLE


def test_unmapped_material_is_rejected() -> None:
    with pytest.raises(IdocBuildError, match="no SAP material number"):
        build_quotation_idoc(
            _quote(),
            profile=PROFILE,
            sold_to="300184",
            created_at=datetime.now(UTC),
            matnr_by_material_id={},
        )


@pytest.mark.parametrize(
    ("value", "places", "trim", "expected"),
    [
        (Decimal("60"), 3, True, "60"),
        (Decimal("37.50"), 3, True, "37.5"),
        (Decimal("38.9"), 4, False, "38.9000"),
        (Decimal("1E+3"), 2, False, "1000.00"),
        (Decimal("0.00005"), 4, False, "0.0001"),
    ],
)
def test_sap_decimal(value: Decimal, places: int, trim: bool, expected: str) -> None:
    assert sap_decimal(value, places, trim=trim) == expected
