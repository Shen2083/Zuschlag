"""End to end: SAP master data -> inbound RFQ -> AI quote -> Zuschlag -> ORDERS05 -> SAP.

Everything runs for real except the language model, whose structured output is
replayed from tests/fixtures/rfq/shenai_de.extraction.json (the same RFQ runs
against the real model in test_live_llm.py with RUN_LIVE_LLM=1):

* the mock SAP pushes the customer's own sample IDocs (fixtures/sap/provided)
  through Zuschlag's HTTP inbound endpoints,
* matching, costing, calculation, approval, IDoc rendering and XSD validation
  are production code against PostgreSQL,
* the IDoc goes over HTTP to the mock SAP, which checks it against its master
  data and acknowledges it with ALEAUD01 status 06 and 53 (or 51).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from xml.etree.ElementTree import Element

import httpx
import pytest
from defusedxml.ElementTree import fromstring

from tests.mock_sap import MockSap, MockSapConfig, create_app, push_master_data
from tests.mock_sap.server import PROVIDED
from tests.rfq_support import golden_extraction, rfq_text
from tests.test_sap_reqote import CONTRACT, PROFILE
from zuschlag_api.api.routes.quotes import get_llm_client
from zuschlag_api.llm.client import ZeroRetentionLLMClient
from zuschlag_api.llm.providers import FakeProvider
from zuschlag_api.main import create_app as create_zuschlag
from zuschlag_api.sap.reqote import reqote_schema
from zuschlag_api.sap.transport import HttpPortTransport, get_sap_transport

pytestmark = pytest.mark.integration

PRODUCT_IDOC = PROVIDED / "Product xml.txt"
CUSTOMER_IDOC = PROVIDED / "Customerxml.txt"
RFQ = "Bitte senden Sie uns ein Angebot für 100 Stück Shen AI Product Description"
Q = "/api/v1/quotes"


@dataclass
class World:
    zuschlag: httpx.AsyncClient
    sap: MockSap
    tenant: uuid.UUID


async def _world(tenant: uuid.UUID, sap: MockSap) -> AsyncIterator[World]:
    app = create_zuschlag()
    provider = FakeProvider(
        model="anthropic.claude-opus-5-5", structured=golden_extraction("shenai_de")
    )
    app.dependency_overrides[get_llm_client] = lambda: ZeroRetentionLLMClient(provider)
    sap_http = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(sap)), base_url="http://mock-sap:8090"
    )
    app.dependency_overrides[get_sap_transport] = lambda: HttpPortTransport(
        "http://mock-sap:8090/sap/bc/idoc_xml?sap-client=800", client=sap_http
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"X-Tenant-ID": str(tenant), "X-Actor-ID": "julia.schmidt"},
    ) as zuschlag:
        yield World(zuschlag, sap, tenant)
    await sap_http.aclose()


@pytest.fixture
async def world(tenant_a: uuid.UUID) -> AsyncIterator[World]:
    async for w in _world(tenant_a, MockSap()):
        yield w


async def ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# Segment-by-segment comparison with the interface contract
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Segment:
    path: str  # e.g. "IDOC/E1EDP01/E1EDP19"
    fields: dict[str, str]


def segments(xml: bytes) -> list[Segment]:
    def walk(node: Element, path: str) -> list[Segment]:
        out: list[Segment] = []
        fields = {c.tag: (c.text or "") for c in node if len(c) == 0}
        if node.tag != "IDOC":
            out.append(Segment(path, fields))
        for child in node:
            if len(child) or child.get("segment") or child.get("SEGMENT"):
                out.extend(walk(child, f"{path}/{child.tag}"))
        return out

    root = fromstring(xml)
    [idoc] = root.findall("IDOC")
    return walk(idoc, "IDOC")


def layout(xml: bytes, drop_fields: tuple[str, ...] = ()) -> list[str]:
    """Lines with every value removed: indentation, tags, attributes and order only."""
    lines = xml.decode("utf-8").split("\r\n")
    return [
        re.sub(r">[^<]*</", "></", line)
        for line in lines
        if not any(line.strip().startswith(f"<{f}>") for f in drop_fields)
    ]


# Values that legitimately differ from the contract document, and why.
PER_DOCUMENT = {
    ("IDOC/EDI_DC40", "DOCNUM"): "new IDoc number from sap_outbound_docnum_seq",
    ("IDOC/E1EDK01", "BELNR"): "our quotation number",
    ("IDOC/E1EDKA1[AG]", "PARTN"): "sold-to from Customerxml.txt (contract: 0000100000)",
    ("IDOC/E1EDKA1[AG]", "NAME1"): "sold-to name from Customerxml.txt",
    ("IDOC/E1EDP01/E1EDP19", "KTEXT"): "MAKTX from Product xml.txt (contract: sample text)",
}
# The provided customer carries NAME2 and STRAS, which the contract's customer did not.
EXTRA_SOLD_TO_FIELDS = ("NAME2", "STRAS")


def keyed(segs: list[Segment]) -> list[tuple[str, dict[str, str]]]:
    out = []
    for s in segs:
        path = f"{s.path}[{s.fields['PARVW']}]" if s.path.endswith("E1EDKA1") else s.path
        out.append((path, s.fields))
    return out


# --------------------------------------------------------------------------- #
# The scenario
# --------------------------------------------------------------------------- #


async def test_rfq_to_sap_end_to_end(world: World) -> None:
    z = world.zuschlag

    # 1. SAP pushes the customer's master-data IDocs (outbound from SAP's point of view).
    pushed = await push_master_data(z, [CUSTOMER_IDOC, PRODUCT_IDOC], tenant_id=str(world.tenant))
    assert [(p["idoc_type"], p["created"]) for p in pushed] == [("MATMAS05", 1), ("DEBMAS06", 1)]
    [material] = (await ok(await z.get("/api/v1/materials", params={"q": "shen"})))["items"]
    assert (material["matnr"], material["description"], material["material_type"]) == (
        "shenai",
        "Shen AI Product Description",
        "FERT",
    )
    assert material["standard_price"] is None  # Product xml.txt has no E1MBEWM valuation
    [customer] = (await ok(await z.get("/api/v1/customers", params={"q": "100042"})))["items"]
    assert customer["name1"] == "Shenba 01A212 GmbH"
    assert customer["sales_areas"][0]["payment_terms"] == "NT30"
    await ok(await z.put("/api/v1/tenant/sap-outbound-profile", json=PROFILE.model_dump()))

    # 2. Inbound RFQ (mailbox routing has resolved the sender to KUNNR 0000100042).
    assert rfq_text("shenai_de").strip() == RFQ
    created = await ok(
        await z.post(f"{Q}/generate-from-rfq", json={"raw_text": RFQ, "customer_id": "100042"}),
        201,
    )
    quote_id = created["id"]
    [line] = created["items"]
    assert (line["matnr"], line["match_status"]) == ("shenai", "MATCHED")
    assert Decimal(line["match_confidence"]) > Decimal("0.90")
    assert line["match_method"] == "exact_text"  # the RFQ quotes the SAP short text verbatim
    assert (Decimal(line["quantity"]), line["uom"]) == (Decimal(100), "PCE")
    assert line["unit_cost"] is None
    assert any("no price available" in r for r in created["review_reasons"])

    # 3. No MBEW price in SAP: the estimator enters the base cost (Herstellkosten per piece).
    detail = await ok(await z.get(f"{Q}/{quote_id}"))
    assert detail["items"][0]["catalog_warning"] == "no_price"
    await ok(await z.patch(f"{Q}/{quote_id}/items/{line['id']}", json={"unit_cost": "12.50"}))

    # 4. 20 % Zuschlag, VAT 19 %, payment terms from the customer master (NT30).
    calc = await ok(await z.post(f"{Q}/{quote_id}/calculate", json={"zuschlag_pct": "20"}))
    assert Decimal(calc["factory_cost"]) == Decimal("1250.00")
    assert Decimal(calc["zuschlag_amount"]) == Decimal("250.00")
    assert Decimal(calc["net_amount"]) == Decimal("1500.00")
    assert Decimal(calc["vat_amount"]) == Decimal("285.00")
    assert Decimal(calc["gross_amount"]) == Decimal("1785.00")
    assert Decimal(calc["lines"][0]["unit_price"]) == Decimal("15.00")
    assert (calc["payment_terms"]["zterm"], calc["payment_terms"]["deviation"]) == ("NT30", False)

    approved = await ok(await z.post(f"{Q}/{quote_id}/approve"))
    assert (approved["status"], approved["revision"], approved["export_blockers"]) == (
        "approved",
        1,
        [],
    )

    # 5. Export: the ORDERS05/REQOTE IDoc, compared with quote_as_output.txt.
    preview = await ok(await z.post(f"{Q}/{quote_id}/sap-idoc/prepare"))
    xml = preview["xml"].encode("utf-8")
    reqote_schema().validate(preview["xml"])

    generated, contract = keyed(segments(xml)), keyed(segments(CONTRACT))
    assert (
        [p for p, _ in generated]
        == [p for p, _ in contract]
        == [
            "IDOC/EDI_DC40",
            "IDOC/E1EDK01",
            "IDOC/E1EDKA1[AG]",
            "IDOC/E1EDKA1[LF]",
            "IDOC/E1EDP01",
            "IDOC/E1EDP01/E1EDP19",
        ]
    )
    for (path, mine), (_, theirs) in zip(generated, contract, strict=True):
        extra = EXTRA_SOLD_TO_FIELDS if path.endswith("[AG]") else ()
        # Same fields in the same order; only the sold-to may carry NAME2/STRAS in addition.
        assert [f for f in mine if f not in extra] == list(theirs), path
        for name, value in theirs.items():
            if (path, name) in PER_DOCUMENT:
                continue
            assert mine[name] == value, f"{path}/{name}: {mine[name]!r} != contract {value!r}"

    seg = dict(generated)
    # The fields named in the acceptance criteria, explicitly:
    assert seg["IDOC/E1EDK01"]["ACTION"] == "004"
    assert seg["IDOC/E1EDK01"]["CURCY"] == "EUR"
    assert seg["IDOC/E1EDK01"]["ZTERM"] == "NT30"
    assert seg["IDOC/E1EDKA1[AG]"]["PARVW"] == "AG"
    assert seg["IDOC/E1EDP01"]["POSEX"] == "00010"
    assert seg["IDOC/E1EDP01"]["MENGE"] == "100.000"
    assert seg["IDOC/E1EDP01/E1EDP19"]["IDNLF"] == "shenai"
    # ...and the per-document values, from their sources:
    assert seg["IDOC/EDI_DC40"]["DOCNUM"] == preview["docnum"]
    assert seg["IDOC/E1EDK01"]["BELNR"] == created["quote_number"]
    sold_to = seg["IDOC/E1EDKA1[AG]"]
    assert (sold_to["PARTN"], sold_to["NAME1"], sold_to["NAME2"], sold_to["STRAS"]) == (
        "0000100042",
        "Shenba 01A212 GmbH",
        "IT-Consulting",
        "Musterstraße 10",
    )
    assert (sold_to["ORT01"], sold_to["PSTLZ"], sold_to["LAND1"]) == ("Musterstadt", "12345", "DE")
    assert seg["IDOC/E1EDP01/E1EDP19"]["KTEXT"] == "Shen AI Product Description"

    # Byte layout identical to the contract once values are removed: CRLF line ends,
    # 4-space indentation, SEGMENT/segment attributes, element order, no final newline.
    assert layout(xml, EXTRA_SOLD_TO_FIELDS) == layout(CONTRACT)
    assert not xml.endswith(b"\n")

    # 6. Sync: the mock SAP receives the IDoc and acknowledges 06 then 53.
    sent = await ok(
        await z.post(
            f"{Q}/{quote_id}/sap-idoc/send",
            json={"docnum": preview["docnum"], "sha256": preview["sha256"]},
        )
    )
    assert [(s["status"], s["docnum"]) for s in sent["sap_status"]] == [
        ("06", preview["docnum"]),
        ("53", preview["docnum"]),
    ]
    sap_document = sent["sap_status"][1]["object_key"]
    assert sap_document
    assert sent["quote"]["status"] == "synced"

    [received] = world.sap.inbound.values()
    assert received.xml == xml  # SAP got exactly the reviewed bytes
    assert (received.docnum, received.sender, received.sap_document) == (
        preview["docnum"],
        "CLNT800",
        sap_document,
    )
    [trail] = [e for e in sent["quote"]["trail"] if e["event"] == "sap.idoc.sent"]
    assert [s["status"] for s in trail["details"]["sap_status"]] == ["06", "53"]
    audit = await ok(await z.get("/api/v1/audit-logs"))
    assert {"quote.approved", "sap.reqote.sent"} <= {a["action"] for a in audit}
    assert (await ok(await z.get("/api/v1/audit-logs/verify")))["intact"] is True


async def test_sap_rejection_status_51_keeps_the_quote_unsynced(tenant_a: uuid.UUID) -> None:
    # This SAP system does not know customer 0000100042 (only the material was replicated).
    sap = MockSap(MockSapConfig(master_data=(PRODUCT_IDOC,)))
    async for world in _world(tenant_a, sap):
        z = world.zuschlag
        await push_master_data(z, [PRODUCT_IDOC, CUSTOMER_IDOC], tenant_id=str(world.tenant))
        await ok(await z.put("/api/v1/tenant/sap-outbound-profile", json=PROFILE.model_dump()))
        q = await ok(
            await z.post(f"{Q}/generate-from-rfq", json={"raw_text": RFQ, "customer_id": "100042"}),
            201,
        )
        item = q["items"][0]["id"]
        await ok(await z.patch(f"{Q}/{q['id']}/items/{item}", json={"unit_cost": "12.50"}))
        await ok(await z.post(f"{Q}/{q['id']}/calculate", json={"zuschlag_pct": "20"}))
        await ok(await z.post(f"{Q}/{q['id']}/approve"))
        p = await ok(await z.post(f"{Q}/{q['id']}/sap-idoc/prepare"))

        res = await z.post(
            f"{Q}/{q['id']}/sap-idoc/send", json={"docnum": p["docnum"], "sha256": p["sha256"]}
        )
        assert res.status_code == 502
        assert res.json()["detail"]["reasons"] == ["Auftraggeber 0000100042 unbekannt"]
        after = await ok(await z.get(f"{Q}/{q['id']}"))
        assert after["status"] == "approved"  # not synced: SAP did not post it
        assert not [e for e in after["trail"] if e["event"] == "sap.idoc.sent"]
        [received] = sap.inbound.values()
        assert [s["status"] for s in received.statuses] == ["06", "51"]


async def test_redelivered_idoc_is_not_posted_twice(world: World) -> None:
    """SAP deduplicates by sender + DOCNUM: a retry gets the original answer."""
    sap = create_app(world.sap)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=sap), base_url="http://m") as c:
        body = CONTRACT.replace(b"0000100000", b"0000100042")
        first = await c.post("/sap/bc/idoc_xml", content=body)
        second = await c.post("/sap/bc/idoc_xml", content=body)
    assert first.content == second.content
    assert len(world.sap.inbound) == 1
    assert b"<STATUS>53</STATUS>" in first.content
