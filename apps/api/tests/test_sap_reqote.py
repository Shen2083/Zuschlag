"""ORDERS05 / REQOTE outbound IDoc against the agreed contract quote_as_output.txt."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import xmlschema
from defusedxml.ElementTree import fromstring

from zuschlag_api.sap.reqote import (
    ReqoteDocument,
    ReqoteItem,
    SapOutboundProfile,
    SoldTo,
    format_menge,
    format_posex,
    render_reqote,
    reqote_schema,
)

CONTRACT_PATH = Path(__file__).parent / "fixtures" / "sap" / "quote_as_output.txt"
CONTRACT = CONTRACT_PATH.read_bytes()

# The values carried by the contract document.
PROFILE = SapOutboundProfile(
    mandt="800",
    docrel="750",
    status="30",
    direct="1",
    sender_port="SAPERP",
    sender_partner="CLNT800",
    receiver_port="RECEIVER_PORT",
    receiver_partner="EXT_SYSTEM",
    vendor_number="0000200000",
    vendor_name="Muster Lieferant AG",
)
SOLD_TO = SoldTo(
    partn="0000100000",
    name1="Muster Einkäufer GmbH",
    ort01="Musterstadt",
    pstlz="12345",
    land1="DE",
)
ITEM = ReqoteItem(
    posex=10, menge=Decimal(100), menee="PCE", idnlf="shenai", ktext="Muster-Ersatzteil Premium"
)


def contract_document(**overrides: Any) -> ReqoteDocument:
    fields: dict[str, Any] = {
        "docnum": "0000000000987654",
        "belnr": "0045001234",
        "curcy": "EUR",
        "zterm": "NT30",
        "sold_to": SOLD_TO,
        "items": (ITEM,),
    }
    return ReqoteDocument(**(fields | overrides))


# --------------------------------------------------------------------------- #
# The contract
# --------------------------------------------------------------------------- #


def test_generated_idoc_matches_contract_byte_for_byte() -> None:
    assert render_reqote(contract_document(), PROFILE) == CONTRACT


def test_contract_fixture_is_the_untouched_original() -> None:
    # Guards against editors / git / hooks normalising the reference file.
    assert len(CONTRACT) == 1652
    assert CONTRACT.startswith(b'<?xml version="1.0" encoding="UTF-8"?>\r\n<ORDERS05>')
    assert CONTRACT.count(b"\r\n") == 49
    assert b"\n" not in CONTRACT.replace(b"\r\n", b"")
    assert CONTRACT.endswith(b"</ORDERS05>")  # no trailing newline


def test_contract_validates_against_xsd() -> None:
    reqote_schema().validate(CONTRACT.decode("utf-8"))


def test_contract_field_values() -> None:
    root = fromstring(CONTRACT)
    idoc = root.find("IDOC")
    assert idoc is not None
    dc = idoc.find("EDI_DC40")
    assert dc is not None
    assert (dc.findtext("IDOCTYP"), dc.findtext("MESTYP")) == ("ORDERS05", "REQOTE")
    k01 = idoc.find("E1EDK01")
    assert k01 is not None
    assert [k01.findtext(f) for f in ("ACTION", "CURCY", "ZTERM", "BELNR")] == [
        "004",
        "EUR",
        "NT30",
        "0045001234",
    ]
    partners = {p.findtext("PARVW"): p for p in idoc.findall("E1EDKA1")}
    assert partners["AG"].findtext("PARTN") == "0000100000"
    assert partners["AG"].findtext("NAME1") == "Muster Einkäufer GmbH"
    assert partners["LF"].findtext("PARTN") == "0000200000"
    p01 = idoc.find("E1EDP01")
    assert p01 is not None
    assert [p01.findtext(f) for f in ("POSEX", "MENGE", "MENEE")] == ["00010", "100.000", "PCE"]
    assert p01.findtext("E1EDP19/IDNLF") == "shenai"


# --------------------------------------------------------------------------- #
# Formatting rules beyond the single-item contract
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal(100), "100.000"),
        (Decimal("37.5"), "37.500"),
        (Decimal("0.0005"), "0.001"),
        (Decimal("1E+3"), "1000.000"),
    ],
)
def test_menge_three_decimals(value: Decimal, expected: str) -> None:
    assert format_menge(value) == expected


def test_posex_five_digits() -> None:
    assert [format_posex(p) for p in (10, 20, 990)] == ["00010", "00020", "00990"]


def test_several_items_keep_order_and_positions() -> None:
    second = ReqoteItem(
        posex=20, menge=Decimal("37.5"), menee="HUR", idnlf="SRV-LABOR", ktext="Montage"
    )
    xml = render_reqote(contract_document(items=(ITEM, second)), PROFILE)
    idoc = fromstring(xml).find("IDOC")
    assert idoc is not None
    rows = [
        (p.findtext("POSEX"), p.findtext("MENGE"), p.findtext("MENEE"))
        for p in idoc.findall("E1EDP01")
    ]
    assert rows == [("00010", "100.000", "PCE"), ("00020", "37.500", "HUR")]


def test_optional_address_fields_follow_sap_field_order() -> None:
    sold_to = SOLD_TO.model_copy(update={"name2": "Werk Süd", "stras": "Marienplatz 1"})
    xml = render_reqote(contract_document(sold_to=sold_to), PROFILE).decode()
    ag = xml[xml.index("<PARVW>AG</PARVW>") : xml.index("</E1EDKA1>")]
    order = [
        ag.index(f"<{f}>") for f in ("PARTN", "NAME1", "NAME2", "STRAS", "ORT01", "PSTLZ", "LAND1")
    ]
    assert order == sorted(order)


def test_special_characters_are_escaped() -> None:
    sold_to = SOLD_TO.model_copy(update={"name1": "Müller & Söhne <GmbH>"})
    xml = render_reqote(contract_document(sold_to=sold_to), PROFILE)
    assert b"<NAME1>M\xc3\xbcller &amp; S\xc3\xb6hne &lt;GmbH&gt;</NAME1>" in xml
    assert fromstring(xml).find("IDOC/E1EDKA1/NAME1").text == "Müller & Söhne <GmbH>"  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# The XSD rejects documents that break the contract
# --------------------------------------------------------------------------- #

_CORRUPTIONS = {
    "wrong message type": (b"<MESTYP>REQOTE</MESTYP>", b"<MESTYP>ORDERS</MESTYP>"),
    "two-decimal quantity": (b"<MENGE>100.000</MENGE>", b"<MENGE>100.00</MENGE>"),
    "short item number": (b"<POSEX>00010</POSEX>", b"<POSEX>0010</POSEX>"),
    "wrong qualifier": (b"<QUALF>002</QUALF>", b"<QUALF>001</QUALF>"),
    "wrong action": (b"<ACTION>004</ACTION>", b"<ACTION>000</ACTION>"),
    "segment attribute case": (b'<E1EDK01 segment="1">', b'<E1EDK01 SEGMENT="1">'),
    "missing vendor partner": (
        CONTRACT[
            CONTRACT.index(
                b'        <E1EDKA1 segment="1">\r\n            <PARVW>LF'
            ) : CONTRACT.index(b"        <E1EDP01")
        ],
        b"",
    ),
    "fields out of order": (
        b"<CURCY>EUR</CURCY>\r\n            <ZTERM>NT30</ZTERM>",
        b"<ZTERM>NT30</ZTERM>\r\n            <CURCY>EUR</CURCY>",
    ),
}


@pytest.mark.parametrize("corruption", list(_CORRUPTIONS), ids=list(_CORRUPTIONS))
def test_xsd_rejects_contract_violations(corruption: str) -> None:
    old, new = _CORRUPTIONS[corruption]
    assert old in CONTRACT
    with pytest.raises(xmlschema.XMLSchemaValidationError):
        reqote_schema().validate(CONTRACT.replace(old, new).decode("utf-8"))


def test_invalid_input_never_reaches_xml() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ReqoteItem(posex=10, menge=Decimal(0), menee="PCE", idnlf="shenai", ktext="x")
    with pytest.raises(ValidationError):
        contract_document(docnum="987654")  # must be 16 digits


def test_render_refuses_documents_that_fail_the_xsd() -> None:
    # Bypass the input models (as a future code path might) to prove the XSD is
    # the last line of defence: nothing invalid is ever returned.
    doc = contract_document().model_copy(update={"docnum": "987654"})  # model_copy skips validation
    with pytest.raises(xmlschema.XMLSchemaValidationError):
        render_reqote(doc, PROFILE)
