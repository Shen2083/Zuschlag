"""ORDERS05 quotation IDoc (inbound to SAP SD).

Mirrors `packages/sap-schema/schemas/orders05-quotation.schema.json`, which is
the source of truth shared with the web app. `tests/test_sap_idoc.py` validates
the output of these models against that JSON Schema so the two cannot drift.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SapDate = Annotated[str, StringConstraints(pattern=r"^\d{8}$")]
SapQuantity = Annotated[str, StringConstraints(pattern=r"^\d{1,11}(\.\d{1,3})?$", max_length=15)]
SapAmount = Annotated[str, StringConstraints(pattern=r"^-?\d{1,13}(\.\d{1,4})?$", max_length=18)]


class _Segment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EDI_DC40Segment(_Segment):  # noqa: N801 — SAP segment name
    TABNAM: Literal["EDI_DC40"] = "EDI_DC40"
    MANDT: Annotated[str, StringConstraints(pattern=r"^\d{3}$")]
    DOCNUM: Annotated[str, StringConstraints(pattern=r"^\d{1,16}$")] | None = None
    DIRECT: Literal["2"] = "2"
    IDOCTYP: Literal["ORDERS05"] = "ORDERS05"
    MESTYP: Literal["ORDERS"] = "ORDERS"
    SNDPOR: Annotated[str, StringConstraints(min_length=1, max_length=10)]
    SNDPRT: Literal["LS", "KU"] = "LS"
    SNDPRN: Annotated[str, StringConstraints(min_length=1, max_length=10)]
    RCVPOR: Annotated[str, StringConstraints(min_length=1, max_length=10)]
    RCVPRT: Literal["LS"] = "LS"
    RCVPRN: Annotated[str, StringConstraints(min_length=1, max_length=10)]
    CREDAT: SapDate
    CRETIM: Annotated[str, StringConstraints(pattern=r"^\d{6}$")]


class E1EDK01Segment(_Segment):
    CURCY: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    ZTERM: Annotated[str, StringConstraints(max_length=17)] | None = None
    BELNR: Annotated[str, StringConstraints(max_length=35)] | None = None


class E1EDK14Segment(_Segment):
    QUALF: Literal["006", "007", "008", "012"]
    ORGID: Annotated[str, StringConstraints(min_length=1, max_length=35)]


class E1EDK03Segment(_Segment):
    IDDAT: Annotated[str, StringConstraints(pattern=r"^\d{3}$")]
    DATUM: SapDate


class E1EDKA1Segment(_Segment):
    PARVW: Literal["AG", "WE", "RE", "RG"]
    PARTN: Annotated[str, StringConstraints(min_length=1, max_length=17)]
    NAME1: Annotated[str, StringConstraints(max_length=35)] | None = None


class E1EDK02Segment(_Segment):
    QUALF: Annotated[str, StringConstraints(pattern=r"^\d{3}$")]
    BELNR: Annotated[str, StringConstraints(min_length=1, max_length=35)]
    DATUM: SapDate | None = None


class E1EDP19Segment(_Segment):
    QUALF: Literal["001", "002"]
    IDTNR: Annotated[str, StringConstraints(min_length=1, max_length=35)]
    KTEXT: Annotated[str, StringConstraints(max_length=70)] | None = None


class E1EDP05Segment(_Segment):
    ALCKZ: Literal["+", "-"] | None = None
    KSCHL: Annotated[str, StringConstraints(min_length=1, max_length=4)]
    BETRG: SapAmount | None = None
    KRATE: SapAmount | None = None
    KPERC: Annotated[str, StringConstraints(pattern=r"^-?\d{1,3}(\.\d{1,3})?$")] | None = None


class E1EDP20Segment(_Segment):
    WMENG: SapQuantity
    EDATU: SapDate | None = None


class E1EDP01Segment(_Segment):
    POSEX: Annotated[str, StringConstraints(pattern=r"^\d{1,6}$")]
    MENGE: SapQuantity
    MENEE: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9]{2,3}$")]
    E1EDP19: list[E1EDP19Segment] = Field(min_length=1)
    E1EDP05: list[E1EDP05Segment] | None = None
    E1EDP20: list[E1EDP20Segment] | None = None


class Orders05Quotation(_Segment):
    EDI_DC40: EDI_DC40Segment
    E1EDK01: E1EDK01Segment
    E1EDK14: list[E1EDK14Segment] = Field(min_length=1)
    E1EDK03: list[E1EDK03Segment] | None = None
    E1EDKA1: list[E1EDKA1Segment] = Field(min_length=1)
    E1EDK02: list[E1EDK02Segment] | None = None
    E1EDP01: list[E1EDP01Segment] = Field(min_length=1)

    def to_idoc_json(self) -> dict[str, Any]:
        """JSON-ready dict in the shape of the shared JSON Schema."""
        return self.model_dump(mode="json", exclude_none=True)


# --- formatting helpers ------------------------------------------------------


def sap_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def sap_time(value: datetime) -> str:
    return value.strftime("%H%M%S")


def sap_decimal(value: Decimal, places: int, *, trim: bool = False) -> str:
    """Fixed-point string with '.' separator (never locale-formatted, never exponent).

    `trim=True` drops trailing zeros, e.g. quantities `60.000` -> `60`.
    """
    quantum = Decimal(1).scaleb(-places)
    text = format(value.quantize(quantum, rounding=ROUND_HALF_UP), "f")
    if trim and "." in text:
        text = text.rstrip("0").rstrip(".")
    return text
