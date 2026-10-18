"""POST /api/v1/quotes/generate-from-rfq end to end against PostgreSQL.

The LLM is a FakeProvider replaying the recorded structured outputs for the
German / English fixtures; extraction validation, matching, costing,
persistence, RLS and auditing are all real.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.rfq_support import ConceptEmbedder, golden_extraction, rfq_text, seed_catalog
from zuschlag_api.api.routes.quotes import get_llm_client
from zuschlag_api.api.routes.sap import get_embedder
from zuschlag_api.core.config import get_settings
from zuschlag_api.db.session import tenant_session
from zuschlag_api.llm.client import ZeroRetentionLLMClient
from zuschlag_api.llm.providers import FakeProvider
from zuschlag_api.main import create_app
from zuschlag_api.models import AuditLog, Customer, CustomerSalesArea, Quote, QuoteAuditTrail, Rfq

pytestmark = pytest.mark.integration

Sm = async_sessionmaker[AsyncSession]
ENDPOINT = "/api/v1/quotes/generate-from-rfq"


class Harness:
    def __init__(
        self, app: Any, client: httpx.AsyncClient, tenant: uuid.UUID, embedder: ConceptEmbedder
    ) -> None:
        self.app, self.client, self.tenant, self.embedder = app, client, tenant, embedder
        self.provider = FakeProvider(model="anthropic.claude-opus-5-5")

    def answer_with(self, fixture: str | dict[str, Any], **provider: Any) -> None:
        reply = golden_extraction(fixture) if isinstance(fixture, str) else fixture
        self.provider = FakeProvider(
            model="anthropic.claude-opus-5-5", structured=reply, **provider
        )
        self.app.dependency_overrides[get_llm_client] = lambda: ZeroRetentionLLMClient(
            self.provider
        )

    async def generate(
        self, raw_text: str, tenant: uuid.UUID | None = None, **body: Any
    ) -> httpx.Response:
        return await self.client.post(
            ENDPOINT,
            json={"raw_text": raw_text, **body},
            headers={"X-Tenant-ID": str(tenant or self.tenant), "X-Actor-ID": "julia.schmidt"},
        )


@pytest.fixture
async def h(sessionmaker: Sm, tenant_a: uuid.UUID) -> AsyncIterator[Harness]:
    embedder = ConceptEmbedder()
    async with tenant_session(tenant_a, sessionmaker=sessionmaker) as s:
        await seed_catalog(s, embedder)
        for kunnr, name in (
            ("0000100077", "Rechenzentrum Nord GmbH"),
            ("0000100099", "Nordwind Marine AG"),
        ):
            c = Customer(kunnr=kunnr, name1=name, country="DE")
            s.add(c)
            await s.flush()
            s.add(
                CustomerSalesArea(
                    customer_id=c.id,
                    sales_org="1000",
                    distribution_channel="10",
                    division="00",
                    currency="EUR",
                    payment_terms="NT30",
                )
            )

    app = create_app()
    settings = get_settings().model_copy(update={"rfq_dense_floor": 0.0, "rfq_dense_ceiling": 1.0})
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_embedder] = lambda: embedder
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 4711))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield Harness(app, client, tenant_a, embedder)


def dec(value: Any) -> Decimal:
    return Decimal(str(value))


# --------------------------------------------------------------------------- #
# German custom build: BOM, costing, review
# --------------------------------------------------------------------------- #


async def test_german_rack_inquiry_becomes_costed_custom_bom(h: Harness) -> None:
    h.answer_with("rack_de")
    res = await h.generate(rfq_text("rack_de"))
    assert res.status_code == 201, res.text
    q = res.json()

    # customer metadata, linked to the SAP customer by name
    assert q["customer_name"] == "Rechenzentrum Nord GmbH"
    assert (q["contact_name"], q["contact_email"]) == ("Markus Weber", "m.weber@rz-nord.de")
    assert q["requested_delivery_date"] == "2026-11-27"
    assert q["customer_id"] is not None
    assert (q["language"], q["currency"]) == ("de", "EUR")

    [rack] = q["items"]
    assert (rack["kind"], rack["sourcing"], rack["match_status"]) == (
        "finished_good",
        "custom_build",
        "NOT_APPLICABLE",
    )
    assert dec(rack["quantity"]) == 15
    assert rack["matnr"] is None  # a custom build has no SAP material yet
    assert any(
        c["matnr"] == "FG-RACK-42U" for c in rack["match_candidates"]
    )  # similar product, for reference
    assert {"name": "Belastbarkeit", "value": "250", "unit": "kg", "constraint": "min"} in rack[
        "specs"
    ]

    materials = [c for c in rack["components"] if c["kind"] != "labor"]
    labor = [c for c in rack["components"] if c["kind"] == "labor"]
    by_matnr = {c["matnr"]: c for c in materials}
    assert set(by_matnr) == {"RM-1430-SH20", "RM-1430-TQ40", "PT-CAS-125HD", "PT-HNG-SS180"}
    for c in materials:
        assert (c["match_status"], c["sourcing"]) == ("MATCHED", "catalog")
        assert dec(c["match_confidence"]) >= Decimal("0.75")
    sheet = by_matnr["RM-1430-SH20"]
    assert (sheet["kind"], sheet["material_type"]) == ("raw_material", "ROH")
    assert (dec(sheet["quantity_per_parent"]), dec(sheet["quantity"])) == (Decimal(6), Decimal(90))
    castor = by_matnr["PT-CAS-125HD"]
    assert dec(castor["unit_cost"]) == Decimal("38.9")  # 389.00 per 10 pieces
    assert dec(castor["extended_cost"]) == Decimal("2334.00")  # 60 castors

    assert [c["description"].split(":")[0] for c in labor] == [
        "Cutting",
        "Bending",
        "Welding",
        "Assembly",
        "Quality Inspection",
    ]
    welding = labor[2]
    assert (dec(welding["quantity"]), welding["uom"], dec(welding["labor_rate"])) == (
        Decimal(60),
        "HUR",
        Decimal(92),
    )
    assert dec(welding["extended_cost"]) == Decimal("5520.00")

    # Unit cost = components 1481.00 + labor 830.50; Zuschlag 22 %.
    assert dec(rack["unit_cost"]) == Decimal("2311.5")
    assert dec(rack["margin_pct"]) == 22
    assert dec(rack["unit_margin"]) == Decimal("508.53")
    assert dec(rack["unit_price"]) == Decimal("2820.03")
    assert dec(rack["line_total"]) == Decimal("42300.45")

    assert dec(q["material_cost"]) == Decimal("22215.00")
    assert dec(q["labor_hours"]) == Decimal("150.00")
    assert dec(q["labor_cost"]) == Decimal("12457.50")
    assert dec(q["total_cost"]) == Decimal("34672.50")
    assert dec(q["net_total"]) == Decimal("42300.45")

    # AI-proposed BOM must be confirmed by a person; open questions carried over.
    assert q["status"] == "needs_review"
    assert q["needs_review"] is True
    assert any("custom build must be confirmed" in r for r in q["review_reasons"])
    assert any(r.startswith("Open question:") for r in q["review_reasons"])
    assert len(q["llm_compliance_hash"]) == 64
    assert q["extraction"]["line_items"][0]["is_custom_made"] is True


async def test_llm_request_carries_text_as_data_and_retention_header(h: Harness) -> None:
    h.answer_with("rack_de")
    await h.generate(rfq_text("rack_de"))
    [request] = h.provider.requests
    assert "<rfq>\nBetreff: Anfrage Serverschränke Halle B" in request.messages[0].content
    assert h.provider.last_headers["Data-Retention"] == "false"


async def test_quote_audit_trail_records_each_step_and_is_append_only(
    h: Harness, sessionmaker: Sm
) -> None:
    h.answer_with("rack_de")
    quote_id = (await h.generate(rfq_text("rack_de"))).json()["id"]

    async with tenant_session(h.tenant, sessionmaker=sessionmaker) as s:
        trail = list(
            await s.scalars(
                select(QuoteAuditTrail)
                .where(QuoteAuditTrail.quote_id == uuid.UUID(quote_id))
                .order_by(QuoteAuditTrail.id)
            )
        )
        audit = list(await s.scalars(select(AuditLog).order_by(AuditLog.seq)))
    assert [t.event for t in trail] == [
        "rfq.received",
        "ai.extraction",
        "ai.matching",
        "quote.priced",
        "quote.created",
    ]
    assert trail[1].actor_id == "ai:anthropic.claude-opus-5-5"
    assert trail[2].details is not None
    assert len(trail[2].details["items"]) == 5  # rack + 4 components
    assert trail[3].details is not None
    assert trail[3].details["net_total"] == "42300.45"

    assert [a.action for a in audit] == ["llm.completion", "quote.generated_from_rfq"]
    llm_entry = audit[0]
    assert llm_entry.context is not None
    assert "Edelstahl" not in str(llm_entry.context)  # hashes only, never inquiry text
    assert audit[1].ip_sha256 is not None

    with pytest.raises(DBAPIError, match="permission denied"):
        async with tenant_session(h.tenant, sessionmaker=sessionmaker) as s:
            await s.execute(text("UPDATE quote_audit_trail SET event = 'tampered'"))


# --------------------------------------------------------------------------- #
# Catalog order: exact SAP match vs. missing raw material
# --------------------------------------------------------------------------- #


async def test_catalog_part_matched_exactly_and_missing_raw_material_flagged(h: Harness) -> None:
    h.answer_with("catalog_de")
    q = (await h.generate(rfq_text("catalog_de"))).json()
    castors, sheet = q["items"]

    assert (castors["matnr"], castors["match_method"], castors["sourcing"]) == (
        "PT-CAS-125HD",
        "exact",
        "catalog",
    )
    assert (castors["match_status"], dec(castors["match_confidence"])) == (
        "MATCHED",
        Decimal("1.00"),
    )
    assert dec(castors["unit_price"]) == Decimal("47.4580")  # 38.90 + 22 %
    assert dec(castors["line_total"]) == Decimal("1898.32")
    assert castors["components"] == []

    assert (sheet["kind"], sheet["sourcing"], sheet["match_status"]) == (
        "raw_material",
        "missing_in_catalog",
        "NEEDS_HUMAN_REVIEW",
    )
    assert sheet["matnr"] is None
    assert sheet["unit_price"] is None
    assert sheet["match_candidates"], "reviewer still sees the nearest SAP materials"

    reasons = " | ".join(q["review_reasons"])
    assert "not found in SAP catalog (missing material)" in reasons
    assert "Customer 'Brenner Lebensmitteltechnik' not found" in reasons
    assert q["status"] == "needs_review"
    assert dec(q["net_total"]) == Decimal("1898.32")  # only priced lines


# --------------------------------------------------------------------------- #
# English inquiry, explicit customer, clean draft
# --------------------------------------------------------------------------- #


async def test_english_standard_product_becomes_clean_draft(h: Harness) -> None:
    h.answer_with("worktable_en")
    res = await h.generate(
        rfq_text("worktable_en"), customer_id="100099"
    )  # KUNNR without leading zeros
    q = res.json()
    [table] = q["items"]
    assert (table["matnr"], table["material_type"], table["sourcing"]) == (
        "FG-WT-1200",
        "FERT",
        "catalog",
    )
    assert table["match_status"] == "MATCHED"
    assert dec(table["unit_price"]) == Decimal("780.8")
    assert dec(q["net_total"]) == Decimal("1561.60")
    assert (q["status"], q["review_reasons"]) == ("draft", [])
    assert q["customer_name"] == "Nordwind Marine AG"


async def test_margin_override(h: Harness) -> None:
    h.answer_with("worktable_en")
    q = (
        await h.generate(rfq_text("worktable_en"), customer_id="0000100099", margin_pct="30")
    ).json()
    assert dec(q["margin_pct"]) == 30
    assert dec(q["items"][0]["unit_price"]) == Decimal("832")


# --------------------------------------------------------------------------- #
# Failure handling: nothing half-written
# --------------------------------------------------------------------------- #


async def _counts(sm: Sm, tenant: uuid.UUID) -> tuple[int, int]:
    async with tenant_session(tenant, sessionmaker=sm) as s:
        rfqs = await s.scalar(select(func.count()).select_from(Rfq))
        quotes = await s.scalar(select(func.count()).select_from(Quote))
    return int(rfqs or 0), int(quotes or 0)


async def test_unknown_customer_is_404_and_nothing_is_stored(h: Harness, sessionmaker: Sm) -> None:
    h.answer_with("rack_de")
    res = await h.generate(rfq_text("rack_de"), customer_id="9999999999")
    assert res.status_code == 404
    assert await _counts(sessionmaker, h.tenant) == (0, 0)


async def test_model_refusal_is_502_and_rolled_back(h: Harness, sessionmaker: Sm) -> None:
    h.answer_with("rack_de", stop_reason="refusal")
    res = await h.generate(rfq_text("rack_de"))
    assert res.status_code == 502
    assert await _counts(sessionmaker, h.tenant) == (0, 0)


async def test_invalid_structured_output_is_502(h: Harness) -> None:
    bad = golden_extraction("rack_de")
    bad["line_items"][0]["quantity"] = -15
    h.answer_with(bad)
    assert (await h.generate(rfq_text("rack_de"))).status_code == 502


async def test_llm_not_configured_is_503(h: Harness) -> None:
    h.app.dependency_overrides[get_llm_client] = lambda: None
    assert (await h.generate("15 Racks")).status_code == 503


async def test_oversized_inquiry_is_413(h: Harness) -> None:
    h.answer_with("rack_de")
    small = get_settings().model_copy(update={"rfq_max_chars": 100})
    h.app.dependency_overrides[get_settings] = lambda: small
    assert (await h.generate("x" * 101)).status_code == 413


async def test_quotes_and_catalog_are_tenant_isolated(
    h: Harness, sessionmaker: Sm, tenant_b: uuid.UUID
) -> None:
    h.answer_with("catalog_de")
    await h.generate(rfq_text("catalog_de"))
    # Tenant B has no catalog: even the cited article number is unknown there.
    q = (await h.generate(rfq_text("catalog_de"), tenant=tenant_b)).json()
    assert [i["sourcing"] for i in q["items"]] == ["missing_in_catalog", "missing_in_catalog"]
    assert await _counts(sessionmaker, tenant_b) == (1, 1)
    assert await _counts(sessionmaker, h.tenant) == (1, 1)
