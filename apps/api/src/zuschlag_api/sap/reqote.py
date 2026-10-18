"""Outbound quotation IDoc: basic type ORDERS05, message type REQOTE.

The byte layout follows the agreed interface contract
(`tests/fixtures/sap/quote_as_output.txt`): UTF-8 without BOM, double-quoted
XML declaration, 4-space indentation, CRLF line endings, no trailing newline,
`SEGMENT="1"` on the control record and `segment="1"` on data segments, and
optional fields omitted rather than sent empty. Every document is validated
against `xsd/orders05_reqote.xsd` before it leaves the service.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Literal
from xml.sax.saxutils import escape

import xmlschema
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

CRLF = "\r\n"
INDENT = "    "
XSD_RESOURCE = "orders05_reqote.xsd"

Str = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SapOutboundProfile(_Frozen):
    """ALE partner profile of the sending system (stored per tenant)."""

    mandt: Annotated[str, StringConstraints(pattern=r"^\d{3}$")]
    docrel: Annotated[str, StringConstraints(pattern=r"^\d{1,4}$")] = "750"
    status: Annotated[str, StringConstraints(pattern=r"^\d{2}$")] = "30"
    direct: Literal["1", "2"] = "1"
    # SAP port names are 10 characters (WE21); the contract's 'RECEIVER_PORT' is 13.
    sender_port: Annotated[Str, StringConstraints(max_length=30)]
    sender_partner_type: Annotated[Str, StringConstraints(max_length=2)] = "LS"
    sender_partner: Annotated[Str, StringConstraints(max_length=10)]
    receiver_port: Annotated[Str, StringConstraints(max_length=30)]
    receiver_partner_type: Annotated[Str, StringConstraints(max_length=2)] = "LS"
    receiver_partner: Annotated[Str, StringConstraints(max_length=10)]
    # Our own company as vendor (PARVW LF) in the customer's system.
    vendor_number: Annotated[Str, StringConstraints(max_length=17)]
    vendor_name: Annotated[Str, StringConstraints(max_length=35)]


class SoldTo(_Frozen):
    """E1EDKA1 PARVW=AG (Auftraggeber)."""

    partn: Annotated[Str, StringConstraints(max_length=17)]  # KUNNR
    name1: Annotated[Str, StringConstraints(max_length=35)]
    name2: Annotated[str, StringConstraints(max_length=35)] | None = None
    stras: Annotated[str, StringConstraints(max_length=35)] | None = None
    ort01: Annotated[str, StringConstraints(max_length=35)] | None = None
    pstlz: Annotated[str, StringConstraints(max_length=10)] | None = None
    land1: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2,3}$")] | None = None


class ReqoteItem(_Frozen):
    posex: int = Field(ge=1, le=99999)
    menge: Decimal = Field(gt=0)
    menee: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9]{2,3}$")]
    idnlf: Annotated[Str, StringConstraints(max_length=35)]  # matched SAP MATNR
    ktext: Annotated[Str, StringConstraints(max_length=70)]


class ReqoteDocument(_Frozen):
    docnum: Annotated[str, StringConstraints(pattern=r"^\d{16}$")]
    belnr: Annotated[Str, StringConstraints(max_length=35)]
    curcy: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    zterm: Annotated[Str, StringConstraints(max_length=17)]
    action: Literal["004"] = "004"
    sold_to: SoldTo
    items: tuple[ReqoteItem, ...] = Field(min_length=1)


def format_posex(position: int) -> str:
    return f"{position:05d}"


def format_menge(quantity: Decimal) -> str:
    """Three decimals, '.' separator: 100 -> '100.000'."""
    return format(quantity.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP), "f")


def _lines(doc: ReqoteDocument, profile: SapOutboundProfile) -> Iterator[str]:
    def field(depth: int, name: str, value: str | None) -> Iterator[str]:
        if value is not None and value != "":
            yield f"{INDENT * depth}<{name}>{escape(value)}</{name}>"

    yield '<?xml version="1.0" encoding="UTF-8"?>'
    yield "<ORDERS05>"
    yield f'{INDENT}<IDOC BEGIN="1">'

    yield f'{INDENT * 2}<EDI_DC40 SEGMENT="1">'
    for name, value in (
        ("TABNAM", "EDI_DC40"),
        ("MANDT", profile.mandt),
        ("DOCNUM", doc.docnum),
        ("DOCREL", profile.docrel),
        ("STATUS", profile.status),
        ("DIRECT", profile.direct),
        ("IDOCTYP", "ORDERS05"),
        ("MESTYP", "REQOTE"),
        ("SNDPOR", profile.sender_port),
        ("SNDPRT", profile.sender_partner_type),
        ("SNDPRN", profile.sender_partner),
        ("RCVPOR", profile.receiver_port),
        ("RCVPRT", profile.receiver_partner_type),
        ("RCVPRN", profile.receiver_partner),
    ):
        yield from field(3, name, value)
    yield f"{INDENT * 2}</EDI_DC40>"

    yield f'{INDENT * 2}<E1EDK01 segment="1">'
    yield from field(3, "ACTION", doc.action)
    yield from field(3, "CURCY", doc.curcy)
    yield from field(3, "ZTERM", doc.zterm)
    yield from field(3, "BELNR", doc.belnr)
    yield f"{INDENT * 2}</E1EDK01>"

    ag = doc.sold_to
    # SAP field order of E1EDKA1; optional fields are omitted when empty.
    sold_to_fields: tuple[tuple[str, str | None], ...] = (
        ("PARVW", "AG"),
        ("PARTN", ag.partn),
        ("NAME1", ag.name1),
        ("NAME2", ag.name2),
        ("STRAS", ag.stras),
        ("ORT01", ag.ort01),
        ("PSTLZ", ag.pstlz),
        ("LAND1", ag.land1),
    )
    yield f'{INDENT * 2}<E1EDKA1 segment="1">'
    for ag_name, ag_value in sold_to_fields:
        yield from field(3, ag_name, ag_value)
    yield f"{INDENT * 2}</E1EDKA1>"

    yield f'{INDENT * 2}<E1EDKA1 segment="1">'
    yield from field(3, "PARVW", "LF")
    yield from field(3, "PARTN", profile.vendor_number)
    yield from field(3, "NAME1", profile.vendor_name)
    yield f"{INDENT * 2}</E1EDKA1>"

    for item in doc.items:
        yield f'{INDENT * 2}<E1EDP01 segment="1">'
        yield from field(3, "POSEX", format_posex(item.posex))
        yield from field(3, "MENGE", format_menge(item.menge))
        yield from field(3, "MENEE", item.menee)
        yield f'{INDENT * 3}<E1EDP19 segment="1">'
        yield from field(4, "QUALF", "002")
        yield from field(4, "IDNLF", item.idnlf)
        yield from field(4, "KTEXT", item.ktext)
        yield f"{INDENT * 3}</E1EDP19>"
        yield f"{INDENT * 2}</E1EDP01>"

    yield f"{INDENT}</IDOC>"
    yield "</ORDERS05>"


def render_reqote(doc: ReqoteDocument, profile: SapOutboundProfile) -> bytes:
    """Serialise and validate. Raises `xmlschema.XMLSchemaValidationError` if invalid."""
    xml = CRLF.join(_lines(doc, profile)).encode("utf-8")
    reqote_schema().validate(xml.decode("utf-8"))
    return xml


@lru_cache
def reqote_schema() -> xmlschema.XMLSchema:
    source = files("zuschlag_api.sap").joinpath("xsd", XSD_RESOURCE).read_text(encoding="utf-8")
    return xmlschema.XMLSchema(source)
