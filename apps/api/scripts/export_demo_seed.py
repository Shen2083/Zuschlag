"""Capture the seed data of the static web demo (GitHub Pages) from the real API.

    DATABASE_URL=postgresql+asyncpg://zuschlag_app:...@localhost:5432/zuschlag \
        uv run python scripts/export_demo_seed.py

Runs the actual API in-process against PostgreSQL: the customer's sample IDocs
are ingested through the SAP endpoints, and the German and English sample
RFQs go through the real pipeline (extraction replayed from the recorded
structured outputs, as in the tests; matching, costing and calculation are
production code). The API responses are written to
apps/web/src/lib/demo/seed.json, which the browser-side demo API serves.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # for `tests.*`
os.environ.setdefault("EMBEDDING_PROVIDER", "hashing")
os.environ.setdefault("ENVIRONMENT", "development")

import httpx
from sqlalchemy import select
from tests.mock_sap import push_master_data
from tests.mock_sap.server import MockSapConfig
from tests.rfq_support import ConceptEmbedder, golden_extraction, rfq_text, seed_catalog

from zuschlag_api.api.routes.quotes import get_llm_client
from zuschlag_api.api.routes.sap import get_embedder
from zuschlag_api.core.config import get_settings
from zuschlag_api.db.session import tenant_session
from zuschlag_api.llm.client import ZeroRetentionLLMClient
from zuschlag_api.llm.providers import FakeProvider
from zuschlag_api.main import create_app
from zuschlag_api.models import Customer, CustomerSalesArea, Rfq, RfqSource, Tenant

TARGET = Path(__file__).resolve().parents[3] / "apps/web/src/lib/demo/seed.json"
PROFILE = {
    "mandt": "800",
    "docrel": "750",
    "status": "30",
    "direct": "1",
    "sender_port": "SAPERP",
    "sender_partner_type": "LS",
    "sender_partner": "CLNT800",
    "receiver_port": "RECEIVER_PORT",
    "receiver_partner_type": "LS",
    "receiver_partner": "EXT_SYSTEM",
    "vendor_number": "0000200000",
    "vendor_name": "Muster Lieferant AG",
}
# (fixture, customer reference); None lets the pipeline match the customer by name.
INQUIRIES = [
    ("worktable_en", "100099"),
    ("catalog_de", "100077"),
    ("rack_de", None),
    ("shenai_de", "100042"),
]
EXTRA_CUSTOMERS = [
    ("0000100077", "Rechenzentrum Nord GmbH", "Hafenstraße 12", "20457", "Hamburg", "NT30"),
    ("0000100099", "Nordwind Marine AG", "Am Kai 3", "24103", "Kiel", "NT14"),
]


async def provision(tenant: uuid.UUID, embedder: ConceptEmbedder) -> None:
    async with tenant_session(tenant) as s:
        s.add(
            Tenant(
                tenant_id=tenant,
                name="Muster Lieferant AG",
                sap_client="800",
                sap_sales_org="1000",
                sap_outbound_profile=PROFILE,
            )
        )
        await s.flush()
        await seed_catalog(s, embedder)
        for kunnr, name, street, plz, city, zterm in EXTRA_CUSTOMERS:
            c = Customer(
                kunnr=kunnr, name1=name, street=street, postal_code=plz, city=city, country="DE"
            )
            s.add(c)
            await s.flush()
            s.add(
                CustomerSalesArea(
                    customer_id=c.id,
                    sales_org="1000",
                    distribution_channel="10",
                    division="00",
                    currency="EUR",
                    payment_terms=zterm,
                )
            )


async def main() -> None:
    tenant = uuid.uuid4()
    embedder = ConceptEmbedder()
    await provision(tenant, embedder)

    app = create_app()
    # The concept embedder spans the full cosine range: no calibration offset (as in tests).
    settings = get_settings().model_copy(update={"rfq_dense_floor": 0.0, "rfq_dense_ceiling": 1.0})
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_embedder] = lambda: embedder
    headers = {"X-Tenant-ID": str(tenant), "X-Actor-ID": "julia.schmidt"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost", headers=headers
    ) as api:

        async def get(path: str, **params: Any) -> Any:
            res = await api.get(path, params=params)
            res.raise_for_status()
            return res.json()

        await push_master_data(api, MockSapConfig().master_data, tenant_id=str(tenant))
        quote_ids = []
        for fixture, customer in INQUIRIES:
            provider = FakeProvider(model=settings.llm_model, structured=golden_extraction(fixture))
            app.dependency_overrides[get_llm_client] = lambda p=provider: ZeroRetentionLLMClient(p)
            res = await api.post(
                "/api/v1/quotes/generate-from-rfq",
                json={"raw_text": rfq_text(fixture), "customer_id": customer},
            )
            res.raise_for_status()
            quote_ids.append(res.json()["id"])

        # The showcase quote (the customer's own sample): Product xml.txt carries no MBEW
        # price, so the estimator enters the base cost and applies 20 % Zuschlag, as in
        # test_e2e_rfq_to_sap.py. Visitors start from a priced quote ready for approval.
        showcase = quote_ids[-1]
        line = (await get(f"/api/v1/quotes/{showcase}"))["items"][0]
        patched = await api.patch(
            f"/api/v1/quotes/{showcase}/items/{line['id']}", json={"unit_cost": "12.50"}
        )
        patched.raise_for_status()
        calculated = await api.post(
            f"/api/v1/quotes/{showcase}/calculate", json={"zuschlag_pct": "20"}
        )
        calculated.raise_for_status()

        async with tenant_session(tenant) as s:  # the samples arrived by e-mail
            for rfq in await s.scalars(select(Rfq)):
                rfq.source = RfqSource.EMAIL

        seed = {
            "tenant": await get("/api/v1/tenant"),
            "materials": (await get("/api/v1/materials", limit=500))["items"],
            "customers": (await get("/api/v1/customers", limit=500))["items"],
            "rfqs": await get("/api/v1/rfqs"),
            "quotes": [await get(f"/api/v1/quotes/{q}") for q in quote_ids],
            "audit_logs": await get("/api/v1/audit-logs", limit=500),
            # The demo shifts its dates by (today - captured_at) so they never go stale.
            "captured_at": datetime.now(UTC).isoformat(),
        }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(seed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {TARGET}: {len(seed['quotes'])} quotes, {len(seed['materials'])} materials")


if __name__ == "__main__":
    asyncio.run(main())
