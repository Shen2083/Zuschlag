"""Provider adapters for `ZeroRetentionLLMClient`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from zuschlag_api.core.config import Settings
from zuschlag_api.llm.client import LLMProvider, LLMRequest, LLMResponse

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


class FakeProvider:
    """Deterministic in-process provider for tests and local development."""

    name = "fake"

    def __init__(
        self,
        *,
        region: str = "eu-central-1",
        model: str = "fake-model",
        zero_retention_attested: bool = True,
        reply: str = "ok",
    ) -> None:
        self.region = region
        self.model = model
        self.zero_retention_attested = zero_retention_attested
        self.reply = reply
        self.last_headers: dict[str, str] = {}

    async def complete(self, request: LLMRequest, *, headers: Mapping[str, str]) -> LLMResponse:
        self.last_headers = dict(headers)
        return LLMResponse(
            text=self.reply,
            model=self.model,
            stop_reason="end_turn",
            input_tokens=sum(len(m.content.split()) for m in request.messages),
            output_tokens=len(self.reply.split()),
        )


def provider_from_settings(settings: Settings) -> LLMProvider | None:
    if settings.llm_provider == "bedrock":
        return BedrockClaudeProvider(
            region=settings.llm_aws_region,
            model=settings.llm_model,
            zero_retention_attested=settings.llm_zdr_attested,
        )
    return None
