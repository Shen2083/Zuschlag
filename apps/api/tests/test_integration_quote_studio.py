"""Quote Studio endpoints: read, inline edit, approve, re-parse, IDoc preview + send."""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from tests.rfq_support import rfq_text
from tests.test_integration_rfq_pipeline import Harness, h  # noqa: F401 — fixture
from tests.test_sap_reqote import PROFILE
from zuschlag_api.db.session import tenant_session
from zuschlag_api.models import Customer, QuoteAuditTrail
from zuschlag_api.sap.reqote import reqote_schema
from zuschlag_api.sap.transport import FilePortTransport, get_sap_transport

pytestmark = pytest.mark.integration
Q = "/api/v1/quotes"


def dec(value: Any) -> Decimal:
    return Decimal(str(value))


class Studio:
    def __init__(self, harness: Harness) -> None:
        self.h = harness
        self.headers = {"X-Tenant-ID": str(harness.tenant), "X-Actor-ID": "julia.schmidt"}

    async def get(self, path: str, **params: Any) -> httpx.Response:
        return await self.h.client.get(path, params=params, headers=self.headers)

    async def post(self, path: str, body: Any = None) -> httpx.Response:
        return await self.h.client.post(path, json=body, headers=self.headers)

    async def patch(
        self, quote: dict[str, Any], item: dict[str, Any], **body: Any
    ) -> httpx.Response:
        return await self.h.client.patch(
            f"{Q}/{quote['id']}/items/{item['id']}", json=body, headers=self.headers
        )

    async def put(self, path: str, body: Any) -> httpx.Response:
        return await self.h.client.put(path, json=body, headers=self.headers)

    async def quote(self, fixture: str, **body: Any) -> dict[str, Any]:
        self.h.answer_with(fixture)
        res = await self.h.generate(rfq_text(fixture), **body)
        assert res.status_code == 201, res.text
        detail = await self.get(f"{Q}/{res.json()['id']}")
        assert detail.status_code == 200, detail.text
        data: dict[str, Any] = detail.json()
        return data

    async def calculate(self, quote: dict[str, Any], pct: str = "25") -> None:
        res = await self.post(f"{Q}/{quote['id']}/calculate", {"zuschlag_pct": pct})
        assert res.status_code == 200, res.text

    async def configure_sap(self, outbox: Path) -> None:
        res = await self.put("/api/v1/tenant/sap-outbound-profile", PROFILE.model_dump())
        assert res.status_code == 200, res.text
        self.h.app.dependency_overrides[get_sap_transport] = lambda: FilePortTransport(outbox)


@pytest.fixture
def studio(h: Harness) -> Studio:  # noqa: F811 — pytest fixture injection
    return Studio(h)


def names(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


def by_position(quote: dict[str, Any], position: int) -> dict[str, Any]:
    return next(i for i in quote["items"] if i["position"] == position)


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #


async def test_detail_has_source_rfq_warnings_and_blockers(studio: Studio) -> None:
    q = await studio.quote("catalog_de", customer_id="100077")

    assert q["rfq"]["body_text"] == rfq_text("catalog_de")
    assert q["customer"]["kunnr"] == "0000100077"
    assert q["customer"]["agreed_payment_terms"] == ["NT30"]
    assert [e["event"] for e in q["trail"]][:2] == ["rfq.received", "ai.extraction"]

    castors, sheet = by_position(q, 10), by_position(q, 20)
    assert (castors["matnr"], castors["catalog_warning"]) == ("PT-CAS-125HD", None)
    assert sheet["match_status"] == "NEEDS_HUMAN_REVIEW"
    assert sheet["catalog_warning"] == "missing_in_catalog"  # not found in MATMAS

    assert any("not been calculated" in r for r in q["approve_blockers"])
    assert any("20" in r and "human review" in r for r in q["approve_blockers"])
    assert any("must be approved" in r for r in q["export_blockers"])
    assert any("sap_outbound_profile" in r for r in q["export_blockers"])
    assert q["sap_transport"] is None


async def test_quote_list_filters_and_counts(studio: Studio) -> None:
    a = await studio.quote("catalog_de", customer_id="100077")
    await studio.quote("worktable_en", customer_id="100099")

    everything = (await studio.get(Q)).json()
    assert everything["total"] == 2
    row = next(r for r in everything["items"] if r["id"] == a["id"])
    assert (row["kunnr"], row["items"], row["review_items"]) == ("0000100077", 2, 1)

    found = (await studio.get(Q, q="Nordwind")).json()
    assert [r["customer_name"] for r in found["items"]] == ["Nordwind Marine AG"]
    assert (await studio.get(Q, status="approved")).json()["total"] == 0
    assert (await studio.get(f"{Q}/{uuid.uuid4()}")).status_code == 404


# --------------------------------------------------------------------------- #
# Inline edit
# --------------------------------------------------------------------------- #


async def test_assign_sap_material_resolves_review_and_reprices(studio: Studio) -> None:
    q = await studio.quote("catalog_de", customer_id="100077")
    sheet = by_position(q, 20)

    res = await studio.patch(q, sheet, matnr="RM-1430-SH20")
    assert res.status_code == 200, res.text
    q = res.json()
    sheet = by_position(q, 20)
    assert (sheet["matnr"], sheet["match_status"], sheet["match_method"]) == (
        "RM-1430-SH20",
        "MATCHED",
        "manual",
    )
    assert dec(sheet["match_confidence"]) == 1
    assert (sheet["sourcing"], sheet["catalog_warning"]) == ("catalog", None)
    assert sheet["description"].startswith("Edelstahlblech")  # MAKTX from MATMAS
    assert dec(sheet["unit_cost"]) == Decimal("148.50")
    # 22 % Zuschlag: 40 x 47.4580 + 50 x 181.1700
    assert dec(sheet["unit_price"]) == Decimal("181.17")
    assert dec(q["net_total"]) == Decimal("1898.32") + Decimal("9058.50")
    assert not any("human review" in r for r in q["approve_blockers"])

    edit = next(e for e in reversed(q["trail"]) if e["event"] == "item.edited")
    assert edit["actor_id"] == "julia.schmidt"
    assert edit["details"]["before"]["matnr"] is None
    assert edit["details"]["after"]["matnr"] == "RM-1430-SH20"


async def test_quantity_and_cost_edits_reprice_the_line(studio: Studio) -> None:
    q = await studio.quote("catalog_de", customer_id="100077")
    await studio.calculate(q, "10")
    castors = by_position(q, 10)

    q = (await studio.patch(q, castors, quantity="100", unit_cost="40")).json()
    castors = by_position(q, 10)
    assert (dec(castors["quantity"]), dec(castors["unit_cost"])) == (Decimal(100), Decimal(40))
    assert dec(castors["unit_price"]) == 44  # Zuschlag 10 % kept
    assert dec(castors["line_total"]) == 4400
    assert dec(q["vat_amount"]) == Decimal("836.00")  # 19 % of 4400.00
    assert dec(q["gross_total"]) == Decimal("5236.00")


@pytest.mark.parametrize(
    ("body", "status", "message"),
    [
        ({"matnr": "DOES-NOT-EXIST"}, 422, "not found in the SAP material master"),
        ({"quantity": "0"}, 422, ""),
        ({"uom": "STUECK"}, 422, ""),
        ({"description": ""}, 422, ""),
        ({}, 422, "nothing to change"),
    ],
)
async def test_invalid_edits_are_rejected(
    studio: Studio, body: dict[str, Any], status: int, message: str
) -> None:
    q = await studio.quote("catalog_de", customer_id="100077")
    res = await studio.patch(q, by_position(q, 20), **body)
    assert res.status_code == status
    assert message in res.text


async def test_custom_build_costs_roll_up_from_components(studio: Studio) -> None:
    q = await studio.quote("rack_de")
    rack = q["items"][0]
    base_unit_cost = dec(rack["unit_cost"])
    sheet = next(c for c in rack["components"] if c["matnr"] == "RM-1430-SH20")
    per_unit = dec(sheet["quantity_per_parent"])

    q = (await studio.patch(q, sheet, unit_cost="200")).json()
    rack = q["items"][0]
    assert dec(rack["unit_cost"]) == base_unit_cost + (Decimal(200) - Decimal("148.50")) * per_unit

    # the finished good's quantity scales its components and labor
    q = (await studio.patch(q, rack, quantity="30")).json()
    rack = q["items"][0]
    sheet = next(c for c in rack["components"] if c["matnr"] == "RM-1430-SH20")
    assert dec(sheet["quantity"]) == per_unit * 30
    welding = next(c for c in rack["components"] if c["kind"] == "labor")
    assert dec(welding["labor_hours"]) == (dec(welding["quantity_per_parent"]) * 30).quantize(
        Decimal("0.01")
    )

    blocked = await studio.patch(q, rack, unit_cost="1")
    assert blocked.status_code == 422
    assert "rolled up from its components" in blocked.text

    # Assigning the new FERT keeps the component-based cost
    q = (await studio.patch(q, rack, matnr="FG-RACK-42U")).json()
    rack = q["items"][0]
    assert (rack["matnr"], rack["sourcing"], rack["catalog_warning"]) == (
        "FG-RACK-42U",
        "custom_build",
        None,
    )
    assert dec(rack["unit_cost"]) != Decimal("1180.00")


# --------------------------------------------------------------------------- #
# Approve
# --------------------------------------------------------------------------- #


async def test_approval_gate_and_revocation_on_edit(studio: Studio) -> None:
    q = await studio.quote("catalog_de", customer_id="100077")
    path = f"{Q}/{q['id']}/approve"

    refused = await studio.post(path)
    assert refused.status_code == 422
    reasons = refused.json()["detail"]["reasons"]
    assert any("not been calculated" in r for r in reasons)
    assert any("human review" in r for r in reasons)

    await studio.patch(q, by_position(q, 20), matnr="RM-1430-SH20")
    await studio.calculate(q)
    approved = await studio.post(path, {"comment": "Preise mit Einkauf abgestimmt"})
    assert approved.status_code == 200, approved.text
    q = approved.json()
    assert q["status"] == "approved"
    event = q["trail"][-1]
    assert event["event"] == "quote.approved"
    assert event["details"]["comment"] == "Preise mit Einkauf abgestimmt"
    assert event["details"]["acknowledged_review_reasons"]  # the AI notes that were accepted

    edited = (await studio.patch(q, by_position(q, 10), quantity="41")).json()
    assert edited["status"] == "draft"  # any change needs a new approval
    assert edited["trail"][-1]["details"]["approval_revoked"] is True


# --------------------------------------------------------------------------- #
# Re-parse
# --------------------------------------------------------------------------- #


async def test_reparse_creates_a_new_quote_for_the_same_rfq(studio: Studio) -> None:
    old = await studio.quote("catalog_de", customer_id="100077")
    studio.h.answer_with("catalog_de")
    res = await studio.post(f"{Q}/{old['id']}/reparse")
    assert res.status_code == 201, res.text
    new = res.json()
    assert new["id"] != old["id"]
    assert new["rfq_id"] == old["rfq_id"]
    assert new["customer_id"] == old["customer_id"]

    old_after = (await studio.get(f"{Q}/{old['id']}")).json()
    superseded = old_after["trail"][-1]
    assert superseded["event"] == "quote.superseded"
    assert superseded["details"]["by_quote_id"] == new["id"]
    rfqs = (await studio.get("/api/v1/rfqs")).json()
    assert len(rfqs) == 1
    assert rfqs[0]["quote"]["id"] == new["id"]  # inbox links the latest quote


# --------------------------------------------------------------------------- #
# SAP sync: preview, then send exactly that payload
# --------------------------------------------------------------------------- #


async def _approved(studio: Studio) -> dict[str, Any]:
    q = await studio.quote("catalog_de", customer_id="100077")
    await studio.patch(q, by_position(q, 20), matnr="RM-1430-SH20")
    await studio.calculate(q)
    res = await studio.post(f"{Q}/{q['id']}/approve")
    assert res.status_code == 200, res.text
    data: dict[str, Any] = res.json()
    return data


async def test_preview_then_send_delivers_the_reviewed_bytes(
    studio: Studio, tmp_path: Path
) -> None:
    q = await _approved(studio)
    await studio.configure_sap(tmp_path)
    assert (await studio.get(f"{Q}/{q['id']}")).json()["export_blockers"] == []

    preview = await studio.post(f"{Q}/{q['id']}/sap-idoc/prepare")
    assert preview.status_code == 200, preview.text
    p = preview.json()
    reqote_schema().validate(p["xml"])
    assert (p["receiver"], p["transport"]) == ("EXT_SYSTEM", "file")
    assert "\r\n" in p["xml"]
    assert "<IDNLF>RM-1430-SH20</IDNLF>" in p["xml"]

    sent = await studio.post(
        f"{Q}/{q['id']}/sap-idoc/send", {"docnum": p["docnum"], "sha256": p["sha256"]}
    )
    assert sent.status_code == 200, sent.text
    s = sent.json()
    assert (s["docnum"], s["transport"]) == (p["docnum"], "file")
    assert s["quote"]["status"] == "synced"
    assert s["quote"]["last_idoc_docnum"] == p["docnum"]
    delivered = tmp_path / f"REQOTE_{p['docnum']}.xml"
    assert delivered.read_bytes() == p["xml"].encode("utf-8")  # exactly what was reviewed
    assert names(tmp_path) == [delivered.name]  # no leftover temp file

    # synced quotes are locked
    again = await studio.post(
        f"{Q}/{q['id']}/sap-idoc/send", {"docnum": p["docnum"], "sha256": p["sha256"]}
    )
    assert again.status_code == 409
    assert (await studio.patch(q, by_position(q, 10), quantity="1")).status_code == 409
    events = [e["event"] for e in s["quote"]["trail"]]
    assert events[-2:] == ["sap.idoc.prepared", "sap.idoc.sent"]


async def test_send_refuses_a_payload_that_changed_after_preview(
    studio: Studio, tmp_path: Path
) -> None:
    q = await _approved(studio)
    await studio.configure_sap(tmp_path)
    p = (await studio.post(f"{Q}/{q['id']}/sap-idoc/prepare")).json()

    # The customer master changes in between (e.g. a DEBMAS update renames the company).
    async with tenant_session(studio.h.tenant) as s:
        customer = await s.scalar(select(Customer).where(Customer.kunnr == "0000100077"))
        assert customer is not None
        customer.name1 = "Rechenzentrum Nord GmbH & Co. KG"

    res = await studio.post(
        f"{Q}/{q['id']}/sap-idoc/send", {"docnum": p["docnum"], "sha256": p["sha256"]}
    )
    assert res.status_code == 409
    assert "changed after the IDoc preview" in res.text
    assert names(tmp_path) == []


async def test_send_checks_hash_preview_and_transport(studio: Studio, tmp_path: Path) -> None:
    q = await _approved(studio)
    await studio.configure_sap(tmp_path)
    p = (await studio.post(f"{Q}/{q['id']}/sap-idoc/prepare")).json()
    send = f"{Q}/{q['id']}/sap-idoc/send"

    wrong_hash = await studio.post(send, {"docnum": p["docnum"], "sha256": "0" * 64})
    assert wrong_hash.status_code == 409
    never_prepared = await studio.post(send, {"docnum": "9" * 16, "sha256": p["sha256"]})
    assert never_prepared.status_code == 409

    studio.h.app.dependency_overrides[get_sap_transport] = lambda: None
    assert (
        await studio.post(send, {"docnum": p["docnum"], "sha256": p["sha256"]})
    ).status_code == 503


async def test_prepare_requires_approval(studio: Studio, tmp_path: Path) -> None:
    q = await studio.quote("catalog_de", customer_id="100077")
    await studio.configure_sap(tmp_path)
    res = await studio.post(f"{Q}/{q['id']}/sap-idoc/prepare")
    assert res.status_code == 422
    assert any("must be approved" in r for r in res.json()["detail"]["reasons"])
    async with tenant_session(studio.h.tenant) as s:
        prepared = await s.scalar(
            select(QuoteAuditTrail).where(QuoteAuditTrail.event == "sap.idoc.prepared")
        )
    assert prepared is None


# --------------------------------------------------------------------------- #
# Master data, status, settings
# --------------------------------------------------------------------------- #


async def test_material_and_customer_lists(studio: Studio) -> None:
    mats = (await studio.get("/api/v1/materials", q="edelstahl")).json()
    assert {m["matnr"] for m in mats["items"]} >= {"RM-1430-SH20", "RM-1430-TQ40"}
    assert all(m["has_embedding"] for m in mats["items"])
    fert = (await studio.get("/api/v1/materials", type="fert")).json()
    assert {m["matnr"] for m in fert["items"]} == {"FG-RACK-42U", "FG-WT-1200"}
    assert (await studio.get("/api/v1/materials", q="100%_")).json()["total"] == 0  # escaped

    customers = (await studio.get("/api/v1/customers", q="nord")).json()
    assert customers["total"] == 2
    [area] = customers["items"][0]["sales_areas"]
    assert (area["sales_org"], area["payment_terms"]) == ("1000", "NT30")


async def test_sap_status_and_profile_settings(studio: Studio, tmp_path: Path) -> None:
    status = (await studio.get("/api/v1/sap/status")).json()
    assert status["state"] == "not_configured"

    invalid = await studio.put("/api/v1/tenant/sap-outbound-profile", {"mandt": "8"})
    assert invalid.status_code == 422
    await studio.configure_sap(tmp_path)
    settings = (await studio.get("/api/v1/tenant")).json()
    assert settings["sap_outbound_profile"]["receiver_partner"] == "EXT_SYSTEM"
    assert dec(settings["quoting"]["vat_rate"]) == 19

    status = (await studio.get("/api/v1/sap/status")).json()
    assert (status["state"], status["system_id"], status["client"]) == (
        "connected",
        "CLNT800",
        "800",
    )
    assert status["latency_ms"] is not None

    studio.h.app.dependency_overrides[get_sap_transport] = lambda: FilePortTransport(
        tmp_path / "missing"
    )
    assert (await studio.get("/api/v1/sap/status")).json()["state"] == "unreachable"
