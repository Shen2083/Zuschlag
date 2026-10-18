"""Mock SAP inbound: receive ORDERS05, answer with an ALEAUD01 acknowledgement."""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element
from xml.sax.saxutils import escape

from defusedxml.ElementTree import fromstring
from fastapi import FastAPI, HTTPException, Request, Response

PROVIDED = Path(__file__).resolve().parents[1] / "fixtures" / "sap" / "provided"
STATUS_RECEIVED = "06"
STATUS_POSTED = "53"
STATUS_ERROR = "51"


@dataclass(frozen=True, slots=True)
class MockSapConfig:
    logical_system: str = "EXT_SYSTEM"  # our partner name in the IDoc (RCVPRN)
    client: str = "800"  # MANDT
    master_data: tuple[Path, ...] = (PROVIDED / "Product xml.txt", PROVIDED / "Customerxml.txt")
    username: str | None = None  # basic auth of the ICF service, if set
    password: str | None = None


@dataclass(slots=True)
class InboundIdoc:
    docnum: str
    sender: str
    received_at: str
    xml: bytes
    statuses: list[dict[str, str | None]] = field(default_factory=list)
    sap_document: str | None = None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(node: Element, name: str) -> Element | None:
    return next((c for c in node if _local(c.tag) == name), None)


def _text(node: Element | None, name: str) -> str:
    child = _find(node, name) if node is not None else None
    return (child.text or "").strip() if child is not None else ""


class MockSap:
    """In-memory SAP: master data, received IDocs and their status history."""

    def __init__(self, config: MockSapConfig | None = None) -> None:
        self.config = config or MockSapConfig()
        self.customers: dict[str, str] = {}
        self.materials: dict[str, str] = {}
        self.inbound: dict[tuple[str, str], InboundIdoc] = {}
        self._next_document = 20000001
        for path in self.config.master_data:
            self.load_master_data(path.read_bytes())

    def load_master_data(self, payload: bytes) -> None:
        root = fromstring(payload)
        for node in root.iter():
            tag = _local(node.tag)
            if tag == "E1KNA1M":
                self.customers[_text(node, "KUNNR")] = _text(node, "NAME1")
            elif tag == "E1MARAM":
                maktx = next((_text(t, "MAKTX") for t in node if _local(t.tag) == "E1MAKTM"), "")
                self.materials[_text(node, "MATNR")] = maktx

    # ------------------------------------------------------------------ inbound

    def receive(self, payload: bytes) -> InboundIdoc:
        try:
            root = fromstring(payload)
        except Exception as exc:
            raise HTTPException(
                400, f"not a valid IDoc XML document: {exc.__class__.__name__}"
            ) from exc
        idoc = _find(root, "IDOC")
        dc = _find(idoc, "EDI_DC40") if idoc is not None else None
        if _local(root.tag) != "ORDERS05" or idoc is None or dc is None:
            raise HTTPException(400, "expected an ORDERS05 IDoc with EDI_DC40")
        docnum, sender = _text(dc, "DOCNUM"), _text(dc, "SNDPRN")
        known = self.inbound.get((sender, docnum))
        if known is not None:  # re-delivery of the same IDoc: same answer, nothing posted twice
            return known

        record = InboundIdoc(docnum, sender, datetime.now(UTC).isoformat(), payload)
        self.inbound[(sender, docnum)] = record
        errors = self._check_control(dc)
        if not errors:
            record.statuses.append(
                self._status(record, STATUS_RECEIVED, "IDoc empfangen, Syntax OK")
            )
            errors = self._check_business(idoc)
        if errors:
            record.statuses.append(self._status(record, STATUS_ERROR, "; ".join(errors)))
        else:
            record.sap_document = f"{self._next_document:010d}"
            self._next_document += 1
            record.statuses.append(
                self._status(record, STATUS_POSTED, f"Angebot {record.sap_document} angelegt")
            )
        return record

    def _status(self, record: InboundIdoc, code: str, text: str) -> dict[str, str | None]:
        return {
            "status": code,
            "text": text,
            "object_key": record.sap_document if code == STATUS_POSTED else None,
            "at": datetime.now(UTC).isoformat(),
        }

    def _check_control(self, dc: Element) -> list[str]:
        errors = []
        if (_text(dc, "IDOCTYP"), _text(dc, "MESTYP")) != ("ORDERS05", "REQOTE"):
            errors.append("Basistyp/Nachrichtentyp muss ORDERS05/REQOTE sein")
        if _text(dc, "RCVPRN") != self.config.logical_system:
            errors.append(f"Partnervereinbarung für Empfänger {_text(dc, 'RCVPRN')} fehlt")
        if _text(dc, "MANDT") != self.config.client:
            errors.append(f"Mandant {_text(dc, 'MANDT')} unbekannt")
        if not _text(dc, "DOCNUM").isdigit():
            errors.append("DOCNUM ungültig")
        return errors

    def _check_business(self, idoc: Element) -> list[str]:
        errors = []
        head = _find(idoc, "E1EDK01")
        if not _text(head, "CURCY"):
            errors.append("Währung (CURCY) fehlt")
        if not _text(head, "ZTERM"):
            errors.append("Zahlungsbedingung (ZTERM) fehlt")
        partners = {_text(p, "PARVW"): p for p in idoc if _local(p.tag) == "E1EDKA1"}
        sold_to = _text(partners.get("AG"), "PARTN")
        if sold_to not in self.customers:
            errors.append(f"Auftraggeber {sold_to or '?'} unbekannt")
        items = [p for p in idoc if _local(p.tag) == "E1EDP01"]
        if not items:
            errors.append("keine Positionen")
        for item in items:
            pos = _text(item, "POSEX")
            matnr = _text(_find(item, "E1EDP19"), "IDNLF")
            if matnr not in self.materials:
                errors.append(f"Position {pos}: Material {matnr or '?'} unbekannt")
            try:
                if float(_text(item, "MENGE")) <= 0:
                    raise ValueError
            except ValueError:
                errors.append(f"Position {pos}: Menge ungültig")
        return errors

    # ------------------------------------------------------------- acknowledgement

    def aleaud(self, record: InboundIdoc) -> bytes:
        """ALEAUD01 audit message with one E1STATE per status record."""
        states = "".join(
            '<E1STATE SEGMENT="1">'
            f"<DOCNUM>{escape(record.docnum)}</DOCNUM><STATUS>{s['status']}</STATUS>"
            f"<STATXT>{escape(s['text'] or '')}</STATXT>"
            + (
                f'<E1PRTOB SEGMENT="1"><DOCNUM>{escape(record.docnum)}</DOCNUM>'
                f"<LOGSYS>{escape(self.config.logical_system)}</LOGSYS><OBJTYPE>BUS2031</OBJTYPE>"
                f"<OBJKEY>{s['object_key']}</OBJKEY></E1PRTOB>"
                if s["object_key"]
                else ""
            )
            + "</E1STATE>"
            for s in record.statuses
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?><ALEAUD01><IDOC BEGIN="1">'
            '<EDI_DC40 SEGMENT="1"><TABNAM>EDI_DC40</TABNAM>'
            f"<MANDT>{escape(self.config.client)}</MANDT><IDOCTYP>ALEAUD01</IDOCTYP>"
            f"<MESTYP>ALEAUD</MESTYP><SNDPRN>{escape(self.config.logical_system)}</SNDPRN>"
            f"<RCVPRN>{escape(record.sender)}</RCVPRN></EDI_DC40>"
            f'<E1ADHDR SEGMENT="1"><MESTYP>REQOTE</MESTYP>{states}</E1ADHDR>'
            "</IDOC></ALEAUD01>"
        ).encode()


def create_app(sap: MockSap | None = None) -> FastAPI:
    sap = sap or MockSap()
    app = FastAPI(title="Mock SAP ERP", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.sap = sap

    def authorize(request: Request) -> None:
        cfg = sap.config
        if cfg.username is None:
            return
        expected = base64.b64encode(f"{cfg.username}:{cfg.password}".encode()).decode()
        given = request.headers.get("authorization", "").removeprefix("Basic ")
        if not secrets.compare_digest(given, expected):
            raise HTTPException(401, "unauthorized", headers={"WWW-Authenticate": "Basic"})

    @app.api_route("/sap/bc/idoc_xml", methods=["HEAD"])
    async def probe(request: Request) -> Response:
        authorize(request)
        return Response(status_code=200)

    @app.post("/sap/bc/idoc_xml")
    async def idoc_xml(request: Request) -> Response:
        """SAP XML-HTTP inbound (SICF /sap/bc/idoc_xml)."""
        authorize(request)
        record = sap.receive(await request.body())
        return Response(sap.aleaud(record), media_type="application/xml")

    @app.get("/sap/idocs")
    async def idocs() -> list[dict[str, Any]]:
        return [_summary(r) for r in sap.inbound.values()]

    @app.get("/sap/idocs/{docnum}")
    async def idoc(docnum: str) -> dict[str, Any]:
        for record in sap.inbound.values():
            if record.docnum == docnum.zfill(16):
                return {**_summary(record), "xml": record.xml.decode("utf-8")}
        raise HTTPException(404, "IDoc not found")

    @app.get("/sap/master-data")
    async def master_data() -> dict[str, dict[str, str]]:
        return {"customers": sap.customers, "materials": sap.materials}

    return app


def _summary(record: InboundIdoc) -> dict[str, Any]:
    return {
        "docnum": record.docnum,
        "sender": record.sender,
        "received_at": record.received_at,
        "sap_document": record.sap_document,
        "statuses": record.statuses,
    }
