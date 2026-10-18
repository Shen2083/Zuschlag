from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from tests.sap_samples import DEBMAS_XML, MAKTX_DE, MATMAS_XML, idoc_packet, matmas
from zuschlag_api.sap.idoc_xml import IdocParseError
from zuschlag_api.sap.master_data import (
    IdocValidationError,
    _sap_decimal,
    parse_debmas06,
    parse_matmas05,
)

# --------------------------------------------------------------------------- #
# Complete extraction from the reference samples
# --------------------------------------------------------------------------- #


def test_matmas05_sample_extracts_every_field() -> None:
    [m] = parse_matmas05(MATMAS_XML.encode())

    c = m.control
    assert c.docnum == "0000000004711001"
    assert c.docnum_int == 4711001
    assert (c.idoctyp, c.mestyp) == ("MATMAS05", "MATMAS")
    assert (c.sndprn, c.rcvprn) == ("S4HCLNT100", "ZUSCHLAG")
    assert c.credat == date(2026, 10, 18)

    assert m.msgfn == "005"
    assert m.matnr == "shenai"
    assert m.mtart == "FERT"
    assert m.matkl == "RACK-SS"
    assert m.meins == "PCE"
    assert m.brgew == Decimal("12.500")
    assert m.ntgew == Decimal("10.250")
    assert m.gewei == "KGM"
    assert m.lvorm is False
    assert m.is_deleted is False

    assert [(d.spras, d.spras_iso, d.maktx) for d in m.descriptions] == [
        ("E", "EN", "Shen AI Product Description"),
        ("D", "DE", MAKTX_DE),
    ]
    assert m.descriptions_by_language == {"EN": "Shen AI Product Description", "DE": MAKTX_DE}


def test_matmas_embedding_text_is_matnr_maktx_mtart() -> None:
    [m] = parse_matmas05(MATMAS_XML.encode())
    assert m.embedding_text(["EN", "DE"]) == "shenai Shen AI Product Description FERT"
    assert m.embedding_text(["DE", "EN"]) == f"shenai {MAKTX_DE} FERT"
    assert m.description(["FR"]) == "Shen AI Product Description"  # falls back to first text


def test_debmas06_sample_extracts_every_field() -> None:
    [c] = parse_debmas06(DEBMAS_XML.encode())

    assert c.control.docnum == "0000000004712001"
    assert (c.control.idoctyp, c.control.mestyp) == ("DEBMAS06", "DEBMAS")
    assert c.kunnr == "0000100042"  # leading zeros kept: SAP internal format
    assert c.name1 == "Shenba 01A212 GmbH"
    assert c.name2 == "Werk Süd"
    assert c.stras == "Marienplatz 1"
    assert c.ort01 == "München"
    assert c.pstlz == "80331"
    assert c.land1 == "DE"
    assert c.regio == "09"
    assert c.spras == "D"
    assert c.language == "DE"  # derived from SPRAS, no SPRAS_ISO in the sample
    assert c.is_deleted is False

    assert [(a.vkorg, a.vtweg, a.spart, a.waers, a.zterm) for a in c.sales_areas] == [
        ("1000", "10", "00", "EUR", "NT30"),
        ("1000", "20", "00", "EUR", "NT60"),
    ]


def test_unmodelled_nested_segments_are_ignored() -> None:
    # E1MARCM (plant data) and E1KNB1M (company code) are in the samples but not modelled.
    [m] = parse_matmas05(MATMAS_XML.encode())
    assert "WERKS" not in m.model_dump_json()
    [c] = parse_debmas06(DEBMAS_XML.encode())
    assert "AKONT" not in c.model_dump_json()


# --------------------------------------------------------------------------- #
# Packets, namespaces, extensions
# --------------------------------------------------------------------------- #


def test_multi_idoc_packet() -> None:
    packet = idoc_packet(matmas(), matmas(docnum="0000000004711002", matnr="shenai-2"))
    assert [m.matnr for m in parse_matmas05(packet)] == ["shenai", "shenai-2"]


def test_namespaced_extension_root_from_sap_pi() -> None:
    xml = (
        MATMAS_XML.replace(
            "<MATMAS05>", '<ns0:ZMATMAS05 xmlns:ns0="urn:sap-com:document:sap:idoc:messages">'
        )
        .replace("</MATMAS05>", "</ns0:ZMATMAS05>")
        .replace("<MESTYP>MATMAS</MESTYP>", "<MESTYP>MATMAS</MESTYP><CIMTYP>ZMATMAS05</CIMTYP>")
    )
    [m] = parse_matmas05(xml.encode())
    assert m.matnr == "shenai"
    assert m.control.cimtyp == "ZMATMAS05"


def test_debmas_payload_rejected_by_matmas_parser() -> None:
    with pytest.raises(IdocParseError, match="unexpected root element <DEBMAS06>"):
        parse_matmas05(DEBMAS_XML.encode())


def test_wrong_idoctyp_in_control_record() -> None:
    xml = MATMAS_XML.replace("<IDOCTYP>MATMAS05</IDOCTYP>", "<IDOCTYP>MATMAS03</IDOCTYP>")
    with pytest.raises(IdocValidationError) as exc:
        parse_matmas05(xml.encode())
    assert "IDOCTYP MATMAS03 is not MATMAS05" in exc.value.issues[0].errors[0]["msg"]


def test_document_without_idoc() -> None:
    with pytest.raises(IdocParseError, match="no <IDOC>"):
        parse_matmas05(b"<MATMAS05></MATMAS05>")


def test_malformed_xml() -> None:
    with pytest.raises(IdocParseError, match="rejected XML"):
        parse_matmas05(b"<MATMAS05><IDOC><EDI_DC40>")


# --------------------------------------------------------------------------- #
# XML attacks (defusedxml)
# --------------------------------------------------------------------------- #

XXE_FILE = b"""<?xml version="1.0"?>
<!DOCTYPE MATMAS05 [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<MATMAS05><IDOC><E1MARAM><MATNR>&xxe;</MATNR></E1MARAM></IDOC></MATMAS05>"""

XXE_SSRF = b"""<?xml version="1.0"?>
<!DOCTYPE MATMAS05 SYSTEM "http://169.254.169.254/latest/meta-data/">
<MATMAS05><IDOC/></MATMAS05>"""

BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<MATMAS05><IDOC><E1MARAM><MATNR>&lol3;</MATNR></E1MARAM></IDOC></MATMAS05>"""


@pytest.mark.parametrize(
    "payload", [XXE_FILE, XXE_SSRF, BILLION_LAUGHS], ids=["xxe-file", "xxe-ssrf", "billion-laughs"]
)
def test_dtds_and_entities_are_rejected(payload: bytes) -> None:
    with pytest.raises(IdocParseError, match="DTDForbidden"):
        parse_matmas05(payload)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def test_validation_errors_name_the_idoc_and_field() -> None:
    bad = (
        matmas(docnum="0000000004711009")
        .replace(b"<MEINS>PCE</MEINS>", b"")
        .replace(b"<BRGEW>12.500</BRGEW>", b"<BRGEW>12,5kg</BRGEW>")
    )
    with pytest.raises(IdocValidationError) as exc:
        parse_matmas05(idoc_packet(matmas(), bad))
    [issue] = exc.value.issues  # the valid first IDoc is not reported
    assert issue.docnum == "0000000004711009"
    assert issue.idoc_index == 1
    assert {e["loc"][0] for e in issue.errors} == {"MEINS", "BRGEW"}


def test_net_weight_cannot_exceed_gross_weight() -> None:
    with pytest.raises(IdocValidationError, match="failed validation"):
        parse_matmas05(matmas(brgew="5.000"))


def test_sap_trailing_minus_sign() -> None:
    assert _sap_decimal("1.500-") == Decimal("-1.500")
    assert _sap_decimal(" 12.5 ") == Decimal("12.5")
    with pytest.raises(ValueError, match="not an SAP decimal"):
        _sap_decimal("1,5")


def test_language_from_spras_when_iso_missing() -> None:
    xml = MATMAS_XML.replace("<SPRAS_ISO>DE</SPRAS_ISO>", "")
    [m] = parse_matmas05(xml.encode())
    assert m.descriptions_by_language["DE"] == MAKTX_DE


def test_deletion_flag_and_delete_message() -> None:
    [flagged] = parse_matmas05(matmas(lvorm="X"))
    assert flagged.is_deleted
    [deleted] = parse_matmas05(
        MATMAS_XML.replace("<MSGFN>005</MSGFN>", "<MSGFN>003</MSGFN>", 1).encode()
    )
    assert deleted.is_deleted


def test_content_hash_ignores_envelope_but_not_data_or_deletion() -> None:
    [base] = parse_matmas05(matmas())
    [resent] = parse_matmas05(
        matmas(docnum="0000000004711777").replace(b"<MSGFN>005</MSGFN>", b"<MSGFN>004</MSGFN>", 1)
    )
    [changed] = parse_matmas05(matmas(brgew="13.000"))
    [deleted] = parse_matmas05(matmas(lvorm="X"))
    assert base.content_sha256 == resent.content_sha256
    assert base.content_sha256 != changed.content_sha256
    assert base.content_sha256 != deleted.content_sha256
