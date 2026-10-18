"""Zero-retention LLM client.

All model calls in the codebase go through `ZeroRetentionLLMClient`. Before a
request leaves the process it checks that:

  * the provider is attested as operating under a zero-data-retention (ZDR)
    agreement (`LLM_ZDR_ATTESTED`) — ZDR is contractual and configured per
    provider account; it cannot be switched on by a request header,
  * inference runs in an EU region,
  * the model is not one that the provider only serves *with* retention,
  * the mandatory `Data-Retention: false` header is present and was not
    overridden by the caller.

Every call yields a `ComplianceRecord`: SHA-256 digests of the canonical
prompt and response plus a combined `compliance_hash`. Only the digests are
logged and written to `audit_logs`, never prompt or response text, so an
auditor can later prove *which* exchange happened without the content having
been retained anywhere.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from zuschlag_api.audit.service import record_audit
from zuschlag_api.core.compliance import DATA_RETENTION_HEADER as DATA_RETENTION_HEADER
from zuschlag_api.core.compliance import MANDATORY_HEADERS
from zuschlag_api.core.config import EU_REGIONS, CloudProvider

logger = logging.getLogger("zuschlag.llm")


# Models that the provider does not offer under zero data retention.
# (Anthropic: Claude Fable 5.x requires 30-day retention unless expressly authorised.)
RETENTION_REQUIRED_MODEL_MARKERS: tuple[str, ...] = ("claude-fable", "claude-mythos")

COMPLIANCE_RECORD_VERSION = 1


class LLMMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["user", "assistant"]
    content: str


class LLMRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    messages: tuple[LLMMessage, ...] = Field(min_length=1)
    system: str | None = None
    max_tokens: int = Field(default=16_000, ge=1, le=128_000)


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    model: str
    stop_reason: str | None
    input_tokens: int
    output_tokens: int


T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class StructuredResponse(Generic[T]):
    """A schema-validated model output plus the raw response metadata."""

    parsed: T
    response: LLMResponse


class LLMProvider(Protocol):
    """A transport to one model endpoint. Implementations must send `headers`."""

    name: str
    region: str
    model: str
    zero_retention_attested: bool

    async def complete(self, request: LLMRequest, *, headers: Mapping[str, str]) -> LLMResponse: ...

    async def complete_structured(
        self, request: LLMRequest, output_type: type[T], *, headers: Mapping[str, str]
    ) -> StructuredResponse[T]:
        """Return output constrained to `output_type`'s JSON Schema (structured outputs)."""
        ...


class ComplianceError(RuntimeError):
    """The request would violate the data-retention or residency policy."""


class LLMOutputError(RuntimeError):
    """The model declined (refusal), was cut off, or returned unusable output."""


@dataclass(frozen=True, slots=True)
class ComplianceRecord:
    version: int
    tenant_id: uuid.UUID
    actor_id: str
    provider: str
    region: str
    model: str
    timestamp_utc: str
    prompt_sha256: str
    response_sha256: str
    compliance_hash: str = ""

    def envelope(self) -> dict[str, Any]:
        """The canonical, content-free document that `compliance_hash` covers."""
        return {
            "v": self.version,
            "tenant_id": str(self.tenant_id),
            "actor_id": self.actor_id,
            "provider": self.provider,
            "region": self.region,
            "model": self.model,
            "headers": dict(MANDATORY_HEADERS),
            "timestamp_utc": self.timestamp_utc,
            "prompt_sha256": self.prompt_sha256,
            "response_sha256": self.response_sha256,
        }

    def sealed(self) -> ComplianceRecord:
        return replace(self, compliance_hash=_sha256(self.envelope()))

    def verify(self) -> bool:
        return bool(self.compliance_hash) and self.compliance_hash == _sha256(self.envelope())


@dataclass(frozen=True, slots=True)
class LLMResult:
    response: LLMResponse
    compliance: ComplianceRecord


@dataclass(frozen=True, slots=True)
class StructuredLLMResult(Generic[T]):
    output: T
    response: LLMResponse
    compliance: ComplianceRecord


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha256(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj)).hexdigest()


class ZeroRetentionLLMClient:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def _preflight(self, extra_headers: Mapping[str, str] | None) -> dict[str, str]:
        p = self._provider
        if not p.zero_retention_attested:
            raise ComplianceError(
                f"provider {p.name!r} is not attested for zero data retention "
                "(set LLM_ZDR_ATTESTED=true only once the agreement is in place)"
            )
        if p.region not in EU_REGIONS[CloudProvider.AWS] | EU_REGIONS[CloudProvider.AZURE]:
            raise ComplianceError(f"provider region {p.region!r} is outside the EU")
        model = p.model.lower()
        if any(marker in model for marker in RETENTION_REQUIRED_MODEL_MARKERS):
            raise ComplianceError(f"model {p.model!r} is not available under zero data retention")

        headers = dict(extra_headers or {})
        for name, value in MANDATORY_HEADERS.items():
            for given_name, given in headers.items():
                if given_name.lower() == name.lower() and given != value:
                    raise ComplianceError(f"header {name} must be {value!r}")
            headers = {k: v for k, v in headers.items() if k.lower() != name.lower()}
            headers[name] = value
        return headers

    async def complete(
        self,
        request: LLMRequest,
        *,
        tenant_id: uuid.UUID,
        actor_id: str,
        audit_session: AsyncSession | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> LLMResult:
        headers = self._preflight(extra_headers)
        response = await self._provider.complete(request, headers=headers)
        record = await self._seal(
            {"request": request.model_dump(mode="json")},
            response,
            tenant_id=tenant_id,
            actor_id=actor_id,
            audit_session=audit_session,
        )
        return LLMResult(response=response, compliance=record)

    async def complete_structured(
        self,
        request: LLMRequest,
        output_type: type[T],
        *,
        tenant_id: uuid.UUID,
        actor_id: str,
        audit_session: AsyncSession | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> StructuredLLMResult[T]:
        """Like `complete`, but the output is validated against `output_type`."""
        headers = self._preflight(extra_headers)
        result = await self._provider.complete_structured(request, output_type, headers=headers)
        if result.response.stop_reason == "refusal":
            raise LLMOutputError("model declined the request (refusal)")
        if result.response.stop_reason == "max_tokens":
            raise LLMOutputError("model output was truncated (max_tokens)")
        record = await self._seal(
            {"request": request.model_dump(mode="json"), "output_schema": output_type.__name__},
            result.response,
            tenant_id=tenant_id,
            actor_id=actor_id,
            audit_session=audit_session,
        )
        return StructuredLLMResult(
            output=result.parsed, response=result.response, compliance=record
        )

    async def _seal(
        self,
        prompt: dict[str, Any],
        response: LLMResponse,
        *,
        tenant_id: uuid.UUID,
        actor_id: str,
        audit_session: AsyncSession | None,
    ) -> ComplianceRecord:
        p = self._provider
        prompt_sha256 = _sha256(prompt)
        response_sha256 = _sha256(
            {"text": response.text, "model": response.model, "stop_reason": response.stop_reason}
        )
        record = ComplianceRecord(
            version=COMPLIANCE_RECORD_VERSION,
            tenant_id=tenant_id,
            actor_id=actor_id,
            provider=p.name,
            region=p.region,
            model=response.model,
            timestamp_utc=datetime.now(UTC).isoformat(timespec="microseconds"),
            prompt_sha256=prompt_sha256,
            response_sha256=response_sha256,
        ).sealed()
        logger.info(
            "llm.completion",
            extra={
                "tenant_id": str(tenant_id),
                "provider": p.name,
                "region": p.region,
                "model": response.model,
                "compliance_hash": record.compliance_hash,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
            },
        )
        if audit_session is not None:
            await record_audit(
                audit_session,
                actor_id=actor_id,
                action="llm.completion",
                entity_type="llm_call",
                entity_id=record.compliance_hash,
                context={
                    "provider": p.name,
                    "region": p.region,
                    "model": response.model,
                    "prompt_sha256": prompt_sha256,
                    "response_sha256": response_sha256,
                    "data_retention": False,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                },
            )
        return record
