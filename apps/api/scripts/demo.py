"""`make demo`: provision a tenant, let the mock SAP push master data, run the RFQ pipeline.

Runs inside the demo container next to the API (docker-compose.demo.yml):

1. Provisions the demo tenant with the SAP partner profile of the mock SAP.
2. The mock SAP pushes the customer's sample IDocs (Product xml.txt,
   Customerxml.txt) to the API over HTTP, as SAP would.
3. Runs the RFQ -> quote pipeline on "Bitte senden Sie uns ein Angebot für
   100 Stück Shen AI Product Description":
   - with a configured, ZDR-attested LLM: through the API, with the real model;
   - otherwise in-process with the recorded structured extraction (the same
     replay the end-to-end test uses), against the same database.
4. Prints the Quote Studio URL.

Idempotent: a second run reuses the tenant and creates one more quote.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # for `tests.*`

from tests.mock_sap import push_master_data
from tests.mock_sap.server import MockSapConfig
from tests.rfq_support import golden_extraction, rfq_text

from zuschlag_api.api.routes.quotes import pipeline_config
from zuschlag_api.core.config import get_settings
from zuschlag_api.db.session import tenant_session
from zuschlag_api.embeddings import embedder_from_settings
from zuschlag_api.llm.client import ZeroRetentionLLMClient
from zuschlag_api.llm.providers import FakeProvider
from zuschlag_api.models import Rfq, RfqSource, Tenant
from zuschlag_api.rfq.pipeline import QuotePipeline

TENANT = uuid.UUID(os.environ.get("DEV_TENANT_ID", "5e1d0c3a-7b1f-4c2e-9a55-0d3f6c8b2a10"))
API = os.environ.get("ZUSCHLAG_API_URL", "http://api:8000")
WEB = os.environ.get("ZUSCHLAG_WEB_URL", "http://localhost:3000")
CUSTOMER = "0000100042"
# The mock SAP's partner profile: we send as CLNT800 to its logical system EXT_SYSTEM.
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


def step(text: str) -> None:
    print(f"\033[1m==> {text}\033[0m", flush=True)


async def provision() -> None:
    async with tenant_session(TENANT) as s:
        tenant = await s.scalar(select(Tenant).where(Tenant.tenant_id == TENANT))
        if tenant is None:
            s.add(
                Tenant(
                    tenant_id=TENANT,
                    name="Muster Lieferant AG (Demo)",
                    sap_client="800",
                    sap_sales_org="1000",
                    sap_outbound_profile=PROFILE,
                )
            )
        else:
            tenant.sap_outbound_profile = PROFILE


async def generate(api: httpx.AsyncClient) -> tuple[str, str]:
    raw = rfq_text("shenai_de").strip()
    settings = get_settings()
    if settings.llm_provider != "disabled" and settings.llm_zdr_attested:
        res = await api.post(
            "/api/v1/quotes/generate-from-rfq", json={"raw_text": raw, "customer_id": CUSTOMER}
        )
        res.raise_for_status()
        return res.json()["id"], f"live model {settings.llm_model}"

    llm = ZeroRetentionLLMClient(
        FakeProvider(model=settings.llm_model, structured=golden_extraction("shenai_de"))
    )
    async with tenant_session(TENANT) as s:
        pipeline = QuotePipeline(
            s, llm=llm, embedder=embedder_from_settings(settings), config=pipeline_config(settings)
        )
        quote = await pipeline.generate(raw, actor_id="demo", ip_sha256=None, customer_ref=CUSTOMER)
        rfq = await s.scalar(select(Rfq).where(Rfq.id == quote.rfq_id))
        if rfq is not None:
            rfq.source = RfqSource.EMAIL
        return str(quote.id), "recorded extraction (no LLM configured)"


async def main() -> None:
    step(f"Provisioning demo tenant {TENANT}")
    await provision()

    headers = {"X-Tenant-ID": str(TENANT), "X-Actor-ID": "demo"}
    async with httpx.AsyncClient(base_url=API, headers=headers, timeout=180) as api:
        step("Mock SAP pushes MATMAS05 + DEBMAS06 (Product xml.txt, Customerxml.txt)")
        for r in await push_master_data(api, MockSapConfig().master_data, tenant_id=str(TENANT)):
            counts = f"created={r['created']} updated={r['updated']}"
            print(f"    {r['idoc_type']:9} {r['file']:18} {counts}")

        step("Inbound RFQ -> AI extraction -> SAP matching -> costing")
        quote_id, source = await generate(api)
        quote = (await api.get(f"/api/v1/quotes/{quote_id}")).json()
        [line] = quote["items"]
        print(f"    extraction: {source}")
        match = f"{line['match_status']}, confidence {line['match_confidence']}"
        print(
            f"    {quote['quote_number']}: {line['quantity']} {line['uom']}"
            f" -> MATNR {line['matnr']} ({match}, {line['match_method']})"
        )
        for reason in quote["review_reasons"]:
            print(f"    review: {reason}")

    print()
    print("Quote Studio:", f"\033[1;4m{WEB}/quotes/{quote_id}\033[0m")
    print(
        "Next: enter the base cost (the SAP material has no MBEW price), set the Zuschlag,\n"
        "approve (Shift+A) and sync to SAP (Shift+S). The mock SAP answers with ALEAUD\n"
        "status 06/53; see http://localhost:8090/sap/idocs"
    )


if __name__ == "__main__":
    asyncio.run(main())
