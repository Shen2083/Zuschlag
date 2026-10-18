"""SAP master-data ingestion end to end: HTTP -> parser -> idempotent upserts."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.sap_samples import (
    DEBMAS_DOCNUM,
    MAKTX_DE,
    MATMAS_DOCNUM,
    debmas,
    idoc_packet,
    matmas,
)
from zuschlag_api.api.routes.sap import get_embedder
from zuschlag_api.core.config import get_settings
from zuschlag_api.db.session import tenant_session
from zuschlag_api.embeddings import HashingEmbedder
from zuschlag_api.main import create_app
from zuschlag_api.models import AuditLog, Customer, CustomerSalesArea, Material, SapIdocReceipt

pytestmark = pytest.mark.integration

Sm = async_sessionmaker[AsyncSession]
XML = {"Content-Type": "application/xml"}
EMBED_TEXT = f"shenai {MAKTX_DE} FERT"


class CountingEmbedder(HashingEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.texts: list[str] = []

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return await super().embed_documents(texts)


class Api:
    def __init__(
        self, client: httpx.AsyncClient, tenant: uuid.UUID, embedder: CountingEmbedder
    ) -> None:
        self.client, self.tenant, self.embedder = client, tenant, embedder

    async def post(self, path: str, body: bytes, **kw: Any) -> httpx.Response:
        headers = {
            "X-Tenant-ID": str(self.tenant),
            "X-Actor-ID": "sap-pi",
            **XML,
            **kw.pop("headers", {}),
        }
        return await self.client.post(f"/api/v1/sap/{path}", content=body, headers=headers, **kw)


@pytest.fixture
async def embedder() -> CountingEmbedder:
    return CountingEmbedder()


@pytest.fixture
async def api(tenant_a: uuid.UUID, embedder: CountingEmbedder) -> AsyncIterator[Api]:
    app = create_app()
    app.dependency_overrides[get_embedder] = lambda: embedder
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield Api(c, tenant_a, embedder)


async def _material(sm: Sm, tenant: uuid.UUID, matnr: str = "shenai") -> Material | None:
    async with tenant_session(tenant, sessionmaker=sm) as s:
        return await s.scalar(select(Material).where(Material.matnr == matnr))


async def _count(sm: Sm, tenant: uuid.UUID, model: Any) -> int:
    async with tenant_session(tenant, sessionmaker=sm) as s:
        return int(await s.scalar(select(func.count()).select_from(model)) or 0)


# --------------------------------------------------------------------------- #
# MATMAS05
# --------------------------------------------------------------------------- #


async def test_matmas_ingest_stores_all_fields_and_embedding(api: Api, sessionmaker: Sm) -> None:
    res = await api.post("matmas", matmas())
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["created"], body["embedded"], body["idocs"]) == (1, 1, 1)
    assert body["documents"] == [
        {
            "sender": "S4HCLNT100",
            "docnum": MATMAS_DOCNUM,
            "object_key": "shenai",
            "outcome": "created",
        }
    ]

    m = await _material(sessionmaker, api.tenant)
    assert m is not None
    assert (m.matnr, m.material_type, m.material_group, m.base_uom) == (
        "shenai",
        "FERT",
        "RACK-SS",
        "PCE",
    )
    assert (m.gross_weight, m.net_weight, m.weight_unit) == (
        Decimal("12.500"),
        Decimal("10.250"),
        "KGM",
    )
    assert m.description == MAKTX_DE  # DE preferred by SAP_DESCRIPTION_LANGUAGES
    assert m.descriptions == {"EN": "Shen AI Product Description", "DE": MAKTX_DE}
    assert m.is_active
    assert (m.source_system, m.source_docnum) == ("S4HCLNT100", 4711001)

    assert api.embedder.texts == [EMBED_TEXT]
    assert m.embedding is not None
    assert len(m.embedding) == 1024
    expected = await HashingEmbedder().embed_query(EMBED_TEXT)
    assert m.embedding == pytest.approx(expected, abs=1e-6)  # float4 storage
    assert m.embedding_model == "hashing-v1-1024"
    assert m.embedding_text_sha256 == hashlib.sha256(EMBED_TEXT.encode()).hexdigest()


async def test_redelivery_is_acknowledged_but_not_reapplied(api: Api, sessionmaker: Sm) -> None:
    await api.post("matmas", matmas())
    before = await _material(sessionmaker, api.tenant)

    res = await api.post("matmas", matmas())
    assert res.status_code == 200
    assert res.json()["duplicate"] == 1
    after = await _material(sessionmaker, api.tenant)
    assert before is not None
    assert after is not None
    assert after.updated_at == before.updated_at
    assert api.embedder.texts == [EMBED_TEXT]  # embedded once only
    assert await _count(sessionmaker, api.tenant, SapIdocReceipt) == 1


async def test_same_content_under_new_docnum_is_unchanged(api: Api, sessionmaker: Sm) -> None:
    await api.post("matmas", matmas())
    before = await _material(sessionmaker, api.tenant)

    res = await api.post("matmas", matmas(docnum="0000000004711002"))
    assert res.json()["unchanged"] == 1
    after = await _material(sessionmaker, api.tenant)
    assert before is not None
    assert after is not None
    assert after.updated_at == before.updated_at  # no content write
    assert after.source_docnum == 4711002  # but the watermark advances
    assert len(api.embedder.texts) == 1


async def test_changed_description_updates_and_reembeds(api: Api, sessionmaker: Sm) -> None:
    await api.post("matmas", matmas())
    first = await _material(sessionmaker, api.tenant)

    res = await api.post(
        "matmas", matmas(docnum="0000000004711002", maktx_de="Serverschrank Edelstahl 42HE")
    )
    assert (res.json()["updated"], res.json()["embedded"]) == (1, 1)
    second = await _material(sessionmaker, api.tenant)
    assert first is not None
    assert second is not None
    assert second.description == "Serverschrank Edelstahl 42HE"
    assert second.embedding != first.embedding
    assert api.embedder.texts[-1] == "shenai Serverschrank Edelstahl 42HE FERT"


async def test_change_outside_embedded_text_keeps_vector(api: Api, sessionmaker: Sm) -> None:
    await api.post("matmas", matmas())
    first = await _material(sessionmaker, api.tenant)

    res = await api.post("matmas", matmas(docnum="0000000004711002", brgew="13.000"))
    assert (res.json()["updated"], res.json()["embedded"]) == (1, 0)
    second = await _material(sessionmaker, api.tenant)
    assert first is not None
    assert second is not None
    assert second.gross_weight == Decimal("13.000")
    assert second.embedding == first.embedding
    assert second.embedded_at == first.embedded_at
    assert len(api.embedder.texts) == 1


async def test_out_of_order_older_idoc_is_stale(api: Api, sessionmaker: Sm) -> None:
    await api.post("matmas", matmas(docnum="0000000004711005", brgew="20.000"))
    res = await api.post("matmas", matmas(docnum="0000000004711003", brgew="15.000"))
    assert res.json()["stale"] == 1
    m = await _material(sessionmaker, api.tenant)
    assert m is not None
    assert (m.gross_weight, m.source_docnum) == (Decimal("20.000"), 4711005)


async def test_docnum_reuse_with_different_content_is_rejected_atomically(
    api: Api, sessionmaker: Sm
) -> None:
    await api.post("matmas", matmas())
    packet = idoc_packet(
        matmas(docnum="0000000004711100", matnr="other-material"),  # valid, would be created
        matmas(brgew="99.000"),  # same DOCNUM as before, different content
    )
    res = await api.post("matmas", packet)
    assert res.status_code == 409
    assert await _material(sessionmaker, api.tenant, "other-material") is None  # rolled back


async def test_packet_keeps_newest_idoc_per_material(api: Api, sessionmaker: Sm) -> None:
    packet = idoc_packet(
        matmas(docnum="0000000004711012", brgew="12.000"),
        matmas(docnum="0000000004711011", brgew="11.000"),
    )
    res = await api.post("matmas", packet)
    outcomes = {d["docnum"]: d["outcome"] for d in res.json()["documents"]}
    assert outcomes == {"0000000004711012": "created", "0000000004711011": "stale"}
    m = await _material(sessionmaker, api.tenant)
    assert m is not None
    assert m.gross_weight == Decimal("12.000")
    assert await _count(sessionmaker, api.tenant, SapIdocReceipt) == 2


async def test_multipart_upload_of_several_files(api: Api, sessionmaker: Sm) -> None:
    files = [
        ("file", ("a.xml", matmas(), "application/xml")),
        ("file", ("b.xml", matmas(docnum="0000000004711200", matnr="shenai-b"), "text/xml")),
    ]
    res = await api.client.post(
        "/api/v1/sap/matmas", files=files, headers={"X-Tenant-ID": str(api.tenant)}
    )
    assert res.status_code == 200, res.text
    assert res.json()["created"] == 2
    assert await _count(sessionmaker, api.tenant, Material) == 2


async def test_deletion_flag_deactivates(api: Api, sessionmaker: Sm) -> None:
    await api.post("matmas", matmas())
    res = await api.post("matmas", matmas(docnum="0000000004711002", lvorm="X"))
    assert res.json()["updated"] == 1
    m = await _material(sessionmaker, api.tenant)
    assert m is not None
    assert m.is_active is False


async def test_without_embedder_a_changed_text_drops_the_stale_vector(
    api: Api, sessionmaker: Sm
) -> None:
    await api.post("matmas", matmas())
    api.client._transport.app.dependency_overrides[get_embedder] = lambda: None  # type: ignore[attr-defined]
    res = await api.post("matmas", matmas(docnum="0000000004711002", maktx_de="Neuer Text"))
    assert (res.json()["updated"], res.json()["embedded"]) == (1, 0)
    m = await _material(sessionmaker, api.tenant)
    assert m is not None
    assert m.embedding is None  # never keep a vector that describes old text
    assert m.embedding_model is None


async def test_ingestion_is_audited(api: Api, sessionmaker: Sm) -> None:
    payload = matmas()
    await api.post("matmas", payload)
    async with tenant_session(api.tenant, sessionmaker=sessionmaker) as s:
        entry = await s.scalar(select(AuditLog).where(AuditLog.action == "sap.matmas05.ingested"))
    assert entry is not None
    assert entry.actor_id == "sap-pi"
    assert entry.entity_id == hashlib.sha256(hashlib.sha256(payload).digest()).hexdigest()
    assert entry.context is not None
    assert entry.context["created"] == 1
    assert entry.context["docnum_first"] == MATMAS_DOCNUM


async def test_tenants_are_isolated(api: Api, sessionmaker: Sm, tenant_b: uuid.UUID) -> None:
    await api.post("matmas", matmas())
    assert await _material(sessionmaker, tenant_b) is None
    # The same IDoc for another tenant is an independent delivery.
    res = await api.post("matmas", matmas(), headers={"X-Tenant-ID": str(tenant_b)})
    assert res.json()["created"] == 1
    assert await _material(sessionmaker, tenant_b) is not None


async def test_concurrent_delivery_of_one_docnum_applies_once(api: Api, sessionmaker: Sm) -> None:
    first, second = await asyncio.gather(api.post("matmas", matmas()), api.post("matmas", matmas()))
    codes = sorted([first.status_code, second.status_code])
    assert codes in ([200, 200], [200, 409])  # loser sees a duplicate or is told to retry
    assert await _count(sessionmaker, api.tenant, Material) == 1
    assert await _count(sessionmaker, api.tenant, SapIdocReceipt) == 1


# --- request handling --------------------------------------------------------------


async def test_xxe_payload_rejected(api: Api) -> None:
    xxe = (
        b'<?xml version="1.0"?><!DOCTYPE MATMAS05 [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b"<MATMAS05><IDOC><E1MARAM><MATNR>&x;</MATNR></E1MARAM></IDOC></MATMAS05>"
    )
    res = await api.post("matmas", xxe)
    assert res.status_code == 400
    assert "DTDForbidden" in res.json()["detail"]
    assert "root:" not in res.text


async def test_invalid_idoc_returns_422_with_docnum(api: Api) -> None:
    res = await api.post("matmas", matmas().replace(b"<MEINS>PCE</MEINS>", b""))
    assert res.status_code == 422
    [issue] = res.json()["detail"]
    assert issue["docnum"] == MATMAS_DOCNUM
    assert issue["errors"][0]["loc"] == ["MEINS"]


async def test_unsupported_media_type(api: Api) -> None:
    res = await api.post("matmas", b"{}", headers={"Content-Type": "application/json"})
    assert res.status_code == 415


async def test_payload_size_limit(api: Api) -> None:
    app = api.client._transport.app  # type: ignore[attr-defined]
    small = get_settings().model_copy(update={"sap_idoc_max_bytes": 1024})
    app.dependency_overrides[get_settings] = lambda: small
    res = await api.post("matmas", matmas())  # ~1.5 KB
    assert res.status_code == 413


# --------------------------------------------------------------------------- #
# DEBMAS06
# --------------------------------------------------------------------------- #


async def _customer(sm: Sm, tenant: uuid.UUID) -> tuple[Customer | None, list[CustomerSalesArea]]:
    async with tenant_session(tenant, sessionmaker=sm) as s:
        customer = await s.scalar(select(Customer).where(Customer.kunnr == "0000100042"))
        areas = list(
            await s.scalars(
                select(CustomerSalesArea).order_by(CustomerSalesArea.distribution_channel)
            )
        )
    return customer, areas


async def test_debmas_ingest_stores_customer_and_sales_areas(api: Api, sessionmaker: Sm) -> None:
    res = await api.post("debmas", debmas())
    assert res.status_code == 200, res.text
    assert res.json()["created"] == 1

    c, areas = await _customer(sessionmaker, api.tenant)
    assert c is not None
    assert (c.kunnr, c.name1, c.name2) == ("0000100042", "Shenba 01A212 GmbH", "Werk Süd")
    assert (c.street, c.city, c.postal_code, c.country, c.region) == (
        "Marienplatz 1",
        "München",
        "80331",
        "DE",
        "09",
    )
    assert c.language == "DE"
    assert (c.source_system, c.source_docnum) == ("S4HCLNT100", 4712001)
    assert [
        (
            a.sales_org,
            a.distribution_channel,
            a.division,
            a.currency,
            a.payment_terms,
            a.customer_id,
        )
        for a in areas
    ] == [
        ("1000", "10", "00", "EUR", "NT30", c.id),
        ("1000", "20", "00", "EUR", "NT60", c.id),
    ]


async def test_debmas_redelivery_and_update_replace_sales_areas(api: Api, sessionmaker: Sm) -> None:
    await api.post("debmas", debmas())
    c1, areas1 = await _customer(sessionmaker, api.tenant)

    dup = await api.post("debmas", debmas())
    assert dup.json()["duplicate"] == 1
    _, areas_dup = await _customer(sessionmaker, api.tenant)
    assert [a.id for a in areas_dup] == [a.id for a in areas1]  # untouched

    upd = await api.post(
        "debmas", debmas(docnum="0000000004712002", zterm_10="NT14", drop_channel_20=True)
    )
    assert upd.json()["updated"] == 1
    c2, areas2 = await _customer(sessionmaker, api.tenant)
    assert c1 is not None
    assert c2 is not None
    assert c2.id == c1.id  # upsert, not re-insert
    assert [(a.distribution_channel, a.payment_terms) for a in areas2] == [("10", "NT14")]

    stale = await api.post("debmas", debmas(docnum=DEBMAS_DOCNUM[:-1] + "0"))
    assert stale.json()["stale"] == 1
    _, areas3 = await _customer(sessionmaker, api.tenant)
    assert [(a.distribution_channel, a.payment_terms) for a in areas3] == [("10", "NT14")]


async def test_debmas_endpoint_rejects_matmas(api: Api) -> None:
    res = await api.post("debmas", matmas())
    assert res.status_code == 400


async def test_timestamps_are_timezone_aware(api: Api, sessionmaker: Sm) -> None:
    await api.post("matmas", matmas())
    m = await _material(sessionmaker, api.tenant)
    assert m is not None
    assert isinstance(m.embedded_at, datetime)
    assert m.embedded_at.tzinfo is not None
