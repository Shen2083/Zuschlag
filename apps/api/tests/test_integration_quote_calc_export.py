"""POST /quotes/{id}/calculate and /quotes/{id}/export-sap-idoc against PostgreSQL."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.test_sap_reqote import CONTRACT, PROFILE
from zuschlag_api.db.session import tenant_session
from zuschlag_api.main import create_app
from zuschlag_api.models import (
    AuditLog,
    Customer,
    CustomerSalesArea,
    MatchStatus,
    Quote,
    QuoteAuditTrail,
    QuoteItem,
    QuoteItemKind,
    QuoteStatus,
    Sourcing,
    Tenant,
)
from zuschlag_api.sap.reqote import reqote_schema

pytestmark = pytest.mark.integration
Sm = async_sessionmaker[AsyncSession]


@pytest.fixture
async def contract_quote(sessionmaker: Sm, tenant_a: uuid.UUID) -> uuid.UUID:
    """The world described by quote_as_output.txt, as database rows."""
    async with tenant_session(tenant_a, sessionmaker=sessionmaker) as s:
        tenant = await s.scalar(select(Tenant))
        assert tenant is not None
        tenant.sap_outbound_profile = PROFILE.model_dump(mode="json")
        customer = Customer(
            kunnr="0000100000",
            name1="Muster Einkäufer GmbH",
            city="Musterstadt",
            postal_code="12345",
            country="DE",
        )
        s.add(customer)
        await s.flush()
        s.add(
            CustomerSalesArea(
                customer_id=customer.id,
                sales_org="1000",
                distribution_channel="10",
                division="00",
                currency="EUR",
                payment_terms="NT30",
            )
        )
        quote = Quote(
            quote_number="0045001234",
            customer_id=customer.id,
            currency="EUR",
            margin_pct=Decimal(0),
        )
        s.add(quote)
        await s.flush()
        s.add(
            QuoteItem(
                quote_id=quote.id,
                position=10,
                kind=QuoteItemKind.PURCHASED_PART,
                description="Muster-Ersatzteil Premium",
                quantity=Decimal(100),
                uom="PCE",
                matnr="shenai",
                match_status=MatchStatus.MATCHED,
                match_confidence=Decimal("0.97"),
                sourcing=Sourcing.CATALOG,
                unit_cost=Decimal("12.50"),
                unit_price=Decimal("12.50"),
            )
        )
        return quote.id


@pytest.fixture
async def client(tenant_a: uuid.UUID) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-Tenant-ID": str(tenant_a), "X-Actor-ID": "julia"},
    ) as c:
        yield c


async def _calc(client: httpx.AsyncClient, quote_id: uuid.UUID, **body: Any) -> httpx.Response:
    return await client.post(
        f"/api/v1/quotes/{quote_id}/calculate", json={"zuschlag_pct": "25", **body}
    )


# --------------------------------------------------------------------------- #
# /calculate
# --------------------------------------------------------------------------- #


async def test_calculate_herstellkosten_to_brutto(
    client: httpx.AsyncClient, contract_quote: uuid.UUID, sessionmaker: Sm, tenant_a: uuid.UUID
) -> None:
    res = await _calc(client, contract_quote)
    assert res.status_code == 200, res.text
    c = res.json()
    assert Decimal(c["factory_cost"]) == Decimal("1250.00")  # 100 x 12.50
    assert Decimal(c["zuschlag_amount"]) == Decimal("312.50")
    assert Decimal(c["net_amount"]) == Decimal("1562.50")
    assert (Decimal(c["vat_rate"]), Decimal(c["vat_amount"])) == (Decimal(19), Decimal("296.88"))
    assert Decimal(c["gross_amount"]) == Decimal("1859.38")
    assert c["payment_terms"] == {
        "zterm": "NT30",
        "net_days": 30,
        "description_de": "30 Tage netto",
        "description_en": "net 30 days",
        "agreed": ["NT30"],
        "deviation": False,
    }
    [line] = c["lines"]
    assert Decimal(line["unit_price"]) == Decimal("15.625")

    async with tenant_session(tenant_a, sessionmaker=sessionmaker) as s:
        quote = await s.scalar(select(Quote).where(Quote.id == contract_quote))
        trail = await s.scalar(
            select(QuoteAuditTrail).where(QuoteAuditTrail.event == "quote.calculated")
        )
    assert quote is not None
    assert (quote.net_total, quote.vat_amount, quote.gross_total, quote.payment_terms) == (
        Decimal("1562.50"),
        Decimal("296.88"),
        Decimal("1859.38"),
        "NT30",
    )
    assert trail is not None
    assert trail.details is not None
    assert trail.details["after"]["gross_total"] == "1859.38"


async def test_dynamic_zuschlag_and_reduced_vat(
    client: httpx.AsyncClient, contract_quote: uuid.UUID
) -> None:
    first = (await _calc(client, contract_quote, zuschlag_pct="10")).json()
    second = (await _calc(client, contract_quote, zuschlag_pct="40", vat_rate=7)).json()
    assert Decimal(first["net_amount"]) == Decimal("1375.00")
    assert Decimal(second["net_amount"]) == Decimal("1750.00")
    assert (Decimal(second["vat_amount"]), Decimal(second["gross_amount"])) == (
        Decimal("122.50"),
        Decimal("1872.50"),
    )


@pytest.mark.parametrize(
    "body",
    [{"zuschlag_pct": "100.5"}, {"zuschlag_pct": "-1"}, {"zuschlag_pct": "20", "vat_rate": 16}],
    ids=["zuschlag>100", "negative", "vat-16"],
)
async def test_calculate_input_validation(
    client: httpx.AsyncClient, contract_quote: uuid.UUID, body: dict[str, Any]
) -> None:
    res = await client.post(f"/api/v1/quotes/{contract_quote}/calculate", json=body)
    assert res.status_code == 422


async def test_payment_terms_validated_against_customer_zterm(
    client: httpx.AsyncClient, contract_quote: uuid.UUID
) -> None:
    deviating = await _calc(client, contract_quote, payment_terms="NT60")
    assert deviating.status_code == 422
    assert "deviate from the customer's agreed terms NT30" in deviating.text

    unknown = await _calc(client, contract_quote, payment_terms="ZB99")
    assert unknown.status_code == 422
    assert "unknown payment terms" in unknown.text

    allowed = await _calc(client, contract_quote, payment_terms="NT60", allow_terms_deviation=True)
    assert allowed.status_code == 200
    assert allowed.json()["payment_terms"]["deviation"] is True


async def test_synced_quote_is_locked(
    client: httpx.AsyncClient, contract_quote: uuid.UUID, sessionmaker: Sm, tenant_a: uuid.UUID
) -> None:
    async with tenant_session(tenant_a, sessionmaker=sessionmaker) as s:
        quote = await s.scalar(select(Quote).where(Quote.id == contract_quote))
        assert quote is not None
        quote.status = QuoteStatus.SYNCED
    assert (await _calc(client, contract_quote)).status_code == 409


async def test_unknown_quote_is_404(client: httpx.AsyncClient) -> None:
    assert (await _calc(client, uuid.uuid4())).status_code == 404


# --------------------------------------------------------------------------- #
# /export-sap-idoc
# --------------------------------------------------------------------------- #


async def _set_next_docnum(value: int) -> None:
    admin = create_async_engine(os.environ["TEST_ADMIN_DATABASE_URL"])
    try:
        async with admin.begin() as conn:
            await conn.execute(
                text("SELECT setval('sap_outbound_docnum_seq', :v, false)"), {"v": value}
            )
    finally:
        await admin.dispose()


@pytest.mark.skipif(
    not os.environ.get("TEST_ADMIN_DATABASE_URL"), reason="needs superuser URL to pin DOCNUM"
)
async def test_export_matches_contract_byte_for_byte(
    client: httpx.AsyncClient, contract_quote: uuid.UUID
) -> None:
    assert (await _calc(client, contract_quote)).status_code == 200
    await _set_next_docnum(987654)

    res = await client.post(f"/api/v1/quotes/{contract_quote}/export-sap-idoc")

    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/xml"
    assert res.headers["x-idoc-docnum"] == "0000000000987654"
    assert res.content == CONTRACT


async def test_export_is_xsd_valid_numbered_and_recorded(
    client: httpx.AsyncClient, contract_quote: uuid.UUID, sessionmaker: Sm, tenant_a: uuid.UUID
) -> None:
    await _calc(client, contract_quote)
    first = await client.post(f"/api/v1/quotes/{contract_quote}/export-sap-idoc")
    second = await client.post(f"/api/v1/quotes/{contract_quote}/export-sap-idoc")
    reqote_schema().validate(first.content.decode())
    d1, d2 = first.headers["x-idoc-docnum"], second.headers["x-idoc-docnum"]
    assert len(d1) == 16
    assert int(d2) > int(d1)  # every export is a new IDoc

    async with tenant_session(tenant_a, sessionmaker=sessionmaker) as s:
        quote = await s.scalar(select(Quote).where(Quote.id == contract_quote))
        events = list(
            await s.scalars(
                select(QuoteAuditTrail).where(QuoteAuditTrail.event == "sap.idoc.exported")
            )
        )
        audit = list(
            await s.scalars(select(AuditLog).where(AuditLog.action == "sap.reqote.exported"))
        )
    assert quote is not None
    assert quote.last_idoc_docnum == d2
    assert [e.details["docnum"] for e in events if e.details] == [d1, d2]
    assert len(audit) == 2


async def test_export_lists_every_blocker(
    client: httpx.AsyncClient, contract_quote: uuid.UUID, sessionmaker: Sm, tenant_a: uuid.UUID
) -> None:
    async with tenant_session(tenant_a, sessionmaker=sessionmaker) as s:
        tenant = await s.scalar(select(Tenant))
        assert tenant is not None
        tenant.sap_outbound_profile = None
        item = await s.scalar(select(QuoteItem).where(QuoteItem.quote_id == contract_quote))
        assert item is not None
        item.match_status = MatchStatus.NEEDS_HUMAN_REVIEW

    res = await client.post(f"/api/v1/quotes/{contract_quote}/export-sap-idoc")
    assert res.status_code == 422
    reasons = res.json()["detail"]["reasons"]
    assert any("sap_outbound_profile" in r for r in reasons)
    assert any("/calculate first" in r for r in reasons)  # never calculated
    assert any("NEEDS_HUMAN_REVIEW" in r for r in reasons)


async def test_custom_build_without_sap_material_cannot_be_exported(
    client: httpx.AsyncClient, contract_quote: uuid.UUID, sessionmaker: Sm, tenant_a: uuid.UUID
) -> None:
    async with tenant_session(tenant_a, sessionmaker=sessionmaker) as s:
        item = await s.scalar(select(QuoteItem).where(QuoteItem.quote_id == contract_quote))
        assert item is not None
        item.matnr = None
        item.kind = QuoteItemKind.FINISHED_GOOD
        item.sourcing = Sourcing.CUSTOM_BUILD
        item.match_status = MatchStatus.NOT_APPLICABLE
    await _calc(client, contract_quote)
    res = await client.post(f"/api/v1/quotes/{contract_quote}/export-sap-idoc")
    assert res.status_code == 422
    assert "no SAP material number" in res.text
