from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from zuschlag_api.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def test_healthz_reports_eu_residency(client: httpx.AsyncClient) -> None:
    res = await client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["region"] == "eu-central-1"


async def test_security_headers(client: httpx.AsyncClient) -> None:
    res = await client.get("/healthz")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    assert res.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in res.headers["content-security-policy"]


async def test_cors_allows_only_configured_origin(client: httpx.AsyncClient) -> None:
    preflight = {"Access-Control-Request-Method": "POST"}
    ok = await client.options("/v1/rfqs", headers={"Origin": "http://localhost:3000", **preflight})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"

    evil = await client.options("/v1/rfqs", headers={"Origin": "https://evil.example", **preflight})
    assert evil.status_code == 400
    assert "access-control-allow-origin" not in evil.headers


async def test_untrusted_host_rejected(client: httpx.AsyncClient) -> None:
    res = await client.get("/healthz", headers={"Host": "attacker.example"})
    assert res.status_code == 400


async def test_tenant_header_required(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/rfqs")).status_code == 401
    bad = await client.get("/v1/rfqs", headers={"X-Tenant-ID": "not-a-uuid"})
    assert bad.status_code == 400
