"""Provider adapters for `ZeroRetentionLLMClient`."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from zuschlag_api.core.config import Settings
from zuschlag_api.llm.client import (
    LLMOutputError,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    StructuredResponse,
    T,
)

if TYPE_CHECKING:
    from anthropic import AsyncAnthropicBedrockMantle
    from anthropic.types import MessageParam


class BedrockClaudeProvider:
    """Claude on Amazon Bedrock (Messages API endpoint) in an EU region.

    Requires the optional `llm` extra (`uv sync --extra llm`). AWS credentials
    come from the standard AWS chain (role, profile or environment).
    """

    name = "aws-bedrock"

    def __init__(self, *, region: str, model: str, zero_retention_attested: bool) -> None:
        from anthropic import AsyncAnthropicBedrockMantle

        self.region = region
        self.model = model
        self.zero_retention_attested = zero_retention_attested
        self._client: AsyncAnthropicBedrockMantle = AsyncAnthropicBedrockMantle(aws_region=region)

    async def complete(self, request: LLMRequest, *, headers: Mapping[str, str]) -> LLMResponse:
        from anthropic import omit

        messages: list[MessageParam] = [
            {"role": m.role, "content": m.content} for m in request.messages
        ]
        message = await self._client.messages.create(
            model=self.model,
            max_tokens=request.max_tokens,
            system=request.system if request.system else omit,
            messages=messages,
            extra_headers=dict(headers),
        )
        text = "".join(block.text for block in message.content if block.type == "text")
        return LLMResponse(
            text=text,
            model=message.model,
            stop_reason=message.stop_reason,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )

    async def complete_structured(
        self, request: LLMRequest, output_type: type[T], *, headers: Mapping[str, str]
    ) -> StructuredResponse[T]:
        from anthropic import omit

        messages: list[MessageParam] = [
            {"role": m.role, "content": m.content} for m in request.messages
        ]
        message = await self._client.messages.parse(
            model=self.model,
            max_tokens=request.max_tokens,
            system=request.system if request.system else omit,
            messages=messages,
            output_format=output_type,
            extra_headers=dict(headers),
        )
        text = "".join(block.text for block in message.content if block.type == "text")
        response = LLMResponse(
            text=text,
            model=message.model,
            stop_reason=message.stop_reason,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )
        parsed = message.parsed_output
        if parsed is None:  # refusal, truncation, or no text block
            raise LLMOutputError(f"no structured output (stop_reason={message.stop_reason})")
        return StructuredResponse(parsed=parsed, response=response)


StructuredReply = BaseModel | dict[str, Any] | Callable[[LLMRequest], BaseModel | dict[str, Any]]


class FakeProvider:
    """Deterministic in-process provider for tests and local development.

    `structured` is what `complete_structured` returns: a model, a dict (validated
    against the requested schema exactly as the SDK would), or a callable that
    builds one from the request.
    """

    name = "fake"

    def __init__(
        self,
        *,
        region: str = "eu-central-1",
        model: str = "fake-model",
        zero_retention_attested: bool = True,
        reply: str = "ok",
        structured: StructuredReply | None = None,
        stop_reason: str = "end_turn",
    ) -> None:
        self.region = region
        self.model = model
        self.zero_retention_attested = zero_retention_attested
        self.reply = reply
        self.structured = structured
        self.stop_reason = stop_reason
        self.last_headers: dict[str, str] = {}
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, *, headers: Mapping[str, str]) -> LLMResponse:
        self.last_headers = dict(headers)
        return LLMResponse(
            text=self.reply,
            model=self.model,
            stop_reason="end_turn",
            input_tokens=sum(len(m.content.split()) for m in request.messages),
            output_tokens=len(self.reply.split()),
        )

    async def complete_structured(
        self, request: LLMRequest, output_type: type[T], *, headers: Mapping[str, str]
    ) -> StructuredResponse[T]:
        self.last_headers = dict(headers)
        self.requests.append(request)
        if self.structured is None:
            raise LLMOutputError("FakeProvider has no structured reply configured")
        reply = self.structured(request) if callable(self.structured) else self.structured
        data = reply.model_dump(mode="json") if isinstance(reply, BaseModel) else reply
        parsed = output_type.model_validate(data)  # same validation the SDK applies
        text = parsed.model_dump_json()
        return StructuredResponse(
            parsed=parsed,
            response=LLMResponse(
                text=text,
                model=self.model,
                stop_reason=self.stop_reason,
                input_tokens=sum(len(m.content.split()) for m in request.messages),
                output_tokens=len(text) // 4,
            ),
        )


def provider_from_settings(settings: Settings) -> LLMProvider | None:
    if settings.llm_provider == "bedrock":
        return BedrockClaudeProvider(
            region=settings.llm_aws_region,
            model=settings.llm_model,
            zero_retention_attested=settings.llm_zdr_attested,
        )
    return None
