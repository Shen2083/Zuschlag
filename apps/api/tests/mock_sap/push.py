"""Mock SAP outbound: push master-data IDocs to Zuschlag like an SAP XML-HTTP port."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx
from defusedxml.ElementTree import fromstring

ENDPOINTS = {"MATMAS05": "/api/v1/sap/matmas", "DEBMAS06": "/api/v1/sap/debmas"}
# SAP sends master data before the documents that use it.
ORDER = {"MATMAS05": 0, "DEBMAS06": 1}


def _idoc_type(payload: bytes) -> str:
    return str(fromstring(payload).tag).rsplit("}", 1)[-1]


async def push_master_data(
    client: httpx.AsyncClient, files: Iterable[Path], *, tenant_id: str
) -> list[dict[str, Any]]:
    """POST each IDoc file to Zuschlag (raw `application/xml`); returns Zuschlag's answers.

    `client` points at Zuschlag (base_url). In dev_headers mode the tenant travels
    in X-Tenant-ID; a real SAP port would authenticate with a certificate or user.
    """
    payloads = sorted(
        ((p, p.read_bytes()) for p in files), key=lambda f: ORDER.get(_idoc_type(f[1]), 9)
    )
    results = []
    for path, payload in payloads:
        idoc_type = _idoc_type(payload)
        endpoint = ENDPOINTS.get(idoc_type)
        if endpoint is None:
            raise ValueError(f"{path.name}: unsupported IDoc type {idoc_type}")
        res = await client.post(
            endpoint,
            content=payload,
            headers={
                "Content-Type": "application/xml",
                "X-Tenant-ID": tenant_id,
                "X-Actor-ID": "sap:mock",
            },
        )
        res.raise_for_status()
        results.append({"file": path.name, "idoc_type": idoc_type, **res.json()})
    return results
