from __future__ import annotations

import uuid

import pytest

from zuschlag_api.llm.client import (
    DATA_RETENTION_HEADER,
    ComplianceError,
    LLMMessage,
    LLMRequest,
    ZeroRetentionLLMClient,
)
from zuschlag_api.llm.providers import FakeProvider

TENANT = uuid.UUID("00000000-0000-4000-8000-000000000001")
REQUEST = LLMRequest(
    system="Extract a bill of materials.",
    messages=(LLMMessage(role="user", content="15 stainless server racks, 500 lbs each"),),
)


async def test_mandatory_header_is_sent() -> None:
    provider = FakeProvider()
    await ZeroRetentionLLMClient(provider).complete(REQUEST, tenant_id=TENANT, actor_id="u1")
    assert provider.last_headers[DATA_RETENTION_HEADER] == "false"


async def test_caller_cannot_override_retention_header() -> None:
    client = ZeroRetentionLLMClient(FakeProvider())
    with pytest.raises(ComplianceError, match="Data-Retention"):
        await client.complete(
            REQUEST, tenant_id=TENANT, actor_id="u1", extra_headers={"data-retention": "true"}
        )


async def test_retention_header_is_normalised_case_insensitively() -> None:
    provider = FakeProvider()
    await ZeroRetentionLLMClient(provider).complete(
        REQUEST, tenant_id=TENANT, actor_id="u1", extra_headers={"DATA-RETENTION": "false"}
    )
    assert [k for k in provider.last_headers if k.lower() == "data-retention"] == ["Data-Retention"]


@pytest.mark.parametrize(
    ("provider", "message"),
    [
        (FakeProvider(zero_retention_attested=False), "not attested"),
        (FakeProvider(region="us-east-1"), "outside the EU"),
        (FakeProvider(model="anthropic.claude-fable-5-1"), "not available under zero"),
    ],
)
async def test_preflight_refuses_non_compliant_calls(provider: FakeProvider, message: str) -> None:
    with pytest.raises(ComplianceError, match=message):
        await ZeroRetentionLLMClient(provider).complete(REQUEST, tenant_id=TENANT, actor_id="u1")
    assert provider.last_headers == {}, "request must not have left the process"


async def test_compliance_record_is_verifiable_and_content_free() -> None:
    result = await ZeroRetentionLLMClient(FakeProvider(reply="BOM: ...")).complete(
        REQUEST, tenant_id=TENANT, actor_id="u1"
    )
    record = result.compliance
    assert record.verify()
    assert len(record.compliance_hash) == 64
    envelope = repr(record.envelope())
    assert "stainless" not in envelope
    assert "BOM" not in envelope


async def test_prompt_hash_is_deterministic_and_tamper_evident() -> None:
    client = ZeroRetentionLLMClient(FakeProvider())
    a = await client.complete(REQUEST, tenant_id=TENANT, actor_id="u1")
    b = await client.complete(REQUEST, tenant_id=TENANT, actor_id="u1")
    assert a.compliance.prompt_sha256 == b.compliance.prompt_sha256

    from dataclasses import replace

    forged = replace(a.compliance, prompt_sha256="0" * 64)
    assert not forged.verify()
