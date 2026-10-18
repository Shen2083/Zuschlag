"""Validated models for SAP master-data IDocs: MATMAS05 and DEBMAS06.

Field names follow SAP (upper-case aliases), so a segment's fields can be fed
to `model_validate` unchanged. Only fields Zuschlag.ai uses are modelled;
everything else in the segment is ignored.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Generic, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from zuschlag_api.sap.idoc_xml import IdocParseError, Segment, accept_basic_type, iter_idocs

# SAP one-character language keys (SPRAS) -> ISO 639-1, for segments that
# carry no SPRAS_ISO.
SAP_LANGUAGE_TO_ISO: dict[str, str] = {
    "D": "DE",
    "E": "EN",
    "F": "FR",
    "I": "IT",
    "S": "ES",
    "N": "NL",
    "P": "PT",
    "L": "PL",
    "C": "CS",
    "K": "DA",
    "V": "SV",
}

# SAP message functions (MSGFN). 003 = delete.
MSGFN_DELETE = "003"


def _sap_decimal(value: object) -> object:
    """SAP numbers in IDoc XML: '.' decimal separator, sign *after* the number."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("-"):
        text = "-" + text[:-1].strip()
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"not an SAP decimal: {value!r}") from exc
    if not number.is_finite():
        raise ValueError(f"not a finite number: {value!r}")
    return number


def _sap_flag(value: object) -> object:
    if isinstance(value, str):
        return value.strip().upper() == "X"
    return value


def _sap_date(value: object) -> object:
    if isinstance(value, str) and len(value) == 8 and value.isdigit():
        if value == "00000000":
            return None
        return date(int(value[:4]), int(value[4:6]), int(value[6:]))
    return value


def _upper(value: str) -> str:
    return value.upper()


SapDecimal = Annotated[Decimal, BeforeValidator(_sap_decimal)]
SapFlag = Annotated[bool, BeforeValidator(_sap_flag)]
Code = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1), AfterValidator(_upper)
]


class SapModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=str.upper,
        validate_by_name=True,
        validate_by_alias=True,
        extra="ignore",
        frozen=True,
        str_strip_whitespace=True,
    )


class IdocControl(SapModel):
    """EDI_DC40 control record (the fields we rely on)."""

    docnum: Annotated[str, StringConstraints(pattern=r"^\d{1,16}$")]
    idoctyp: Code
    cimtyp: str | None = None
    mestyp: Code
    sndprn: Annotated[str, StringConstraints(min_length=1, max_length=10)]
    rcvprn: Annotated[str, StringConstraints(min_length=1, max_length=10)]
    sndprt: str | None = None
    rcvprt: str | None = None
    credat: Annotated[date | None, BeforeValidator(_sap_date)] = None
    cretim: str | None = None

    @field_validator("docnum")
    @classmethod
    def _pad_docnum(cls, v: str) -> str:
        return v.zfill(16)

    @property
    def docnum_int(self) -> int:
        return int(self.docnum)


def _content_sha256(model: BaseModel, *, deleted: bool) -> str:
    """Hash of the business content: independent of the control record and of
    MSGFN (004 vs 005 carry the same data), but sensitive to deletion."""
    data = model.model_dump(mode="json", exclude={"control", "msgfn"})
    data["_deleted"] = deleted
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


# --------------------------------------------------------------------------- #
# MATMAS05 — material master
# --------------------------------------------------------------------------- #


class MaterialDescription(SapModel):
    """E1MAKTM — short text in one language."""

    spras: Annotated[str, StringConstraints(max_length=1)] | None = None
    spras_iso: (
        Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{2}$"), AfterValidator(_upper)] | None
    ) = None
    maktx: Annotated[str, StringConstraints(min_length=1, max_length=40)]

    @model_validator(mode="after")
    def _require_language(self) -> MaterialDescription:
        if self.spras_iso is None and (self.spras or "").upper() not in SAP_LANGUAGE_TO_ISO:
            raise ValueError("E1MAKTM needs SPRAS_ISO or a known SPRAS language key")
        return self

    @property
    def language(self) -> str:
        return self.spras_iso or SAP_LANGUAGE_TO_ISO[(self.spras or "").upper()]


class MaterialMaster(SapModel):
    """E1MARAM — general material data, with its E1MAKTM short texts."""

    control: IdocControl
    msgfn: str | None = None
    matnr: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    mtart: Annotated[str, StringConstraints(max_length=4)] | None = None
    matkl: Annotated[str, StringConstraints(max_length=9)] | None = None
    meins: Annotated[Code, StringConstraints(max_length=3)]
    brgew: Annotated[SapDecimal, Field(ge=0)] | None = None
    ntgew: Annotated[SapDecimal, Field(ge=0)] | None = None
    gewei: Annotated[Code, StringConstraints(max_length=3)] | None = None
    lvorm: SapFlag = False
    descriptions: tuple[MaterialDescription, ...] = ()

    @model_validator(mode="after")
    def _check_consistency(self) -> MaterialMaster:
        if self.brgew is not None and self.ntgew is not None and self.ntgew > self.brgew:
            raise ValueError("net weight NTGEW exceeds gross weight BRGEW")
        if (self.brgew or self.ntgew) and not self.gewei:
            raise ValueError("weight unit GEWEI is required when a weight is given")
        languages = [d.language for d in self.descriptions]
        if len(languages) != len(set(languages)):
            raise ValueError("duplicate E1MAKTM language")
        return self

    @property
    def is_deleted(self) -> bool:
        return self.lvorm or self.msgfn == MSGFN_DELETE

    @property
    def descriptions_by_language(self) -> dict[str, str]:
        return {d.language: d.maktx for d in self.descriptions}

    def description(self, preferred_languages: Iterable[str]) -> str | None:
        texts = self.descriptions_by_language
        for lang in preferred_languages:
            if lang in texts:
                return texts[lang]
        return self.descriptions[0].maktx if self.descriptions else None

    def embedding_text(self, preferred_languages: Iterable[str]) -> str:
        """`"{MATNR} {MAKTX} {MTART}"`, skipping parts SAP did not send."""
        parts = (self.matnr, self.description(preferred_languages), self.mtart)
        return " ".join(p for p in parts if p)

    @property
    def content_sha256(self) -> str:
        return _content_sha256(self, deleted=self.is_deleted)


# --------------------------------------------------------------------------- #
# DEBMAS06 — customer master
# --------------------------------------------------------------------------- #


class CustomerSalesArea(SapModel):
    """E1KNVVM — customer data for one sales area."""

    vkorg: Annotated[str, StringConstraints(min_length=1, max_length=4)]
    vtweg: Annotated[str, StringConstraints(min_length=1, max_length=2)]
    spart: Annotated[str, StringConstraints(min_length=1, max_length=2)]
    waers: (
        Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{3}$"), AfterValidator(_upper)] | None
    ) = None
    zterm: Annotated[str, StringConstraints(max_length=4)] | None = None
    loevm: SapFlag = False

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.vkorg, self.vtweg, self.spart)


class CustomerMaster(SapModel):
    """E1KNA1M — general customer data, with its E1KNVVM sales areas."""

    control: IdocControl
    msgfn: str | None = None
    kunnr: Annotated[str, StringConstraints(min_length=1, max_length=10)]
    name1: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    name2: Annotated[str, StringConstraints(max_length=40)] | None = None
    stras: Annotated[str, StringConstraints(max_length=60)] | None = None
    ort01: Annotated[str, StringConstraints(max_length=40)] | None = None
    pstlz: Annotated[str, StringConstraints(max_length=10)] | None = None
    land1: (
        Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{2,3}$"), AfterValidator(_upper)] | None
    ) = None
    regio: Annotated[str, StringConstraints(max_length=3)] | None = None
    spras: Annotated[str, StringConstraints(max_length=1)] | None = None
    spras_iso: (
        Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{2}$"), AfterValidator(_upper)] | None
    ) = None
    loevm: SapFlag = False
    sales_areas: tuple[CustomerSalesArea, ...] = ()

    @model_validator(mode="after")
    def _unique_sales_areas(self) -> CustomerMaster:
        keys = [a.key for a in self.sales_areas]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate E1KNVVM sales area (VKORG/VTWEG/SPART)")
        return self

    @property
    def is_deleted(self) -> bool:
        return self.loevm or self.msgfn == MSGFN_DELETE

    @property
    def language(self) -> str | None:
        if self.spras_iso:
            return self.spras_iso
        return SAP_LANGUAGE_TO_ISO.get((self.spras or "").upper())

    @property
    def content_sha256(self) -> str:
        return _content_sha256(self, deleted=self.is_deleted)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

M = TypeVar("M", bound=SapModel)


@dataclass(frozen=True, slots=True)
class IdocIssue:
    idoc_index: int
    docnum: str | None
    errors: list[dict[str, Any]]


class IdocValidationError(ValueError):
    """One or more IDocs in the payload failed validation. Nothing is stored."""

    def __init__(self, issues: list[IdocIssue]) -> None:
        self.issues = issues
        super().__init__(f"{len(issues)} IDoc(s) failed validation")


@dataclass(frozen=True, slots=True)
class _IdocSpec(Generic[M]):
    basic_type: str
    message_types: frozenset[str]
    main_segment: str
    build: Callable[[IdocControl, Segment], M]


def _control(idoc: Segment, spec: _IdocSpec[Any]) -> IdocControl:
    dc = idoc.child("EDI_DC40")
    if dc is None:
        raise ValueError("missing EDI_DC40 control record")
    control = IdocControl.model_validate(dc.fields)
    if control.idoctyp != spec.basic_type:
        raise ValueError(f"IDOCTYP {control.idoctyp} is not {spec.basic_type}")
    if control.mestyp not in spec.message_types:
        raise ValueError(f"MESTYP {control.mestyp} not in {sorted(spec.message_types)}")
    return control


def _parse(payload: bytes, spec: _IdocSpec[M]) -> list[M]:
    results: list[M] = []
    issues: list[IdocIssue] = []
    for index, idoc in enumerate(
        iter_idocs(payload, accept_root=accept_basic_type(spec.basic_type))
    ):
        docnum = (idoc.child("EDI_DC40") or Segment("", {}, ())).fields.get("DOCNUM")
        try:
            control = _control(idoc, spec)
            main = idoc.all(spec.main_segment)
            if len(main) != 1:
                raise ValueError(f"expected exactly one {spec.main_segment}, found {len(main)}")
            results.append(spec.build(control, main[0]))
        except ValidationError as exc:
            errors = exc.errors(include_url=False, include_context=False, include_input=False)
            issues.append(IdocIssue(index, docnum, [dict(e) for e in errors]))
        except ValueError as exc:
            issues.append(IdocIssue(index, docnum, [{"type": "value_error", "msg": str(exc)}]))
    if issues:
        raise IdocValidationError(issues)
    return results


def _build_material(control: IdocControl, seg: Segment) -> MaterialMaster:
    return MaterialMaster.model_validate(
        {
            **seg.fields,
            "control": control,
            "descriptions": [t.fields for t in seg.all("E1MAKTM")],
        }
    )


def _build_customer(control: IdocControl, seg: Segment) -> CustomerMaster:
    return CustomerMaster.model_validate(
        {
            **seg.fields,
            "control": control,
            "sales_areas": [a.fields for a in seg.all("E1KNVVM")],
        }
    )


MATMAS05 = _IdocSpec("MATMAS05", frozenset({"MATMAS"}), "E1MARAM", _build_material)
DEBMAS06 = _IdocSpec("DEBMAS06", frozenset({"DEBMAS"}), "E1KNA1M", _build_customer)


def parse_matmas05(payload: bytes) -> list[MaterialMaster]:
    """Parse a MATMAS05 IDoc XML document (one or more IDocs)."""
    return _parse(payload, MATMAS05)


def parse_debmas06(payload: bytes) -> list[CustomerMaster]:
    """Parse a DEBMAS06 IDoc XML document (one or more IDocs)."""
    return _parse(payload, DEBMAS06)


__all__ = [
    "CustomerMaster",
    "CustomerSalesArea",
    "IdocControl",
    "IdocParseError",
    "IdocValidationError",
    "MaterialDescription",
    "MaterialMaster",
    "parse_debmas06",
    "parse_matmas05",
]
