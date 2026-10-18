from __future__ import annotations

import json
import math
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from zuschlag_api.core.config import Settings
from zuschlag_api.embeddings import (
    EMBEDDING_DIMENSIONS,
    EmbeddingError,
    HashingEmbedder,
    OpenAICompatibleEmbedder,
    SentenceTransformerEmbedder,
)


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


async def test_hashing_embedder_is_deterministic_unit_length_and_similarity_aware() -> None:
    e = HashingEmbedder()
    a, b, c = await e.embed_documents(
        [
            "shenai Shen AI Produktbeschreibung FERT",
            "shenai Shen AI Produktbeschreibung FERT",
            "Schraube M8 DIN 933 verzinkt",
        ]
    )
    assert len(a) == EMBEDDING_DIMENSIONS
    assert a == b
    assert math.isclose(math.sqrt(_cos(a, a)), 1.0, rel_tol=1e-9)
    near = await e.embed_query("Shen AI Produktbeschreibung")
    assert _cos(near, a) > _cos(near, c)


# --- private OpenAI-compatible endpoint ---------------------------------------


def _endpoint(handler: Any, **kwargs: Any) -> OpenAICompatibleEmbedder:
    return OpenAICompatibleEmbedder(
        base_url="https://embeddings.eu.example.internal/v1",
        model="text-embed-eu",
        api_key="test-only-key",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


async def test_openai_compatible_sends_retention_header_and_reorders_by_index() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        data = [
            {"index": i, "embedding": [float(i)] * EMBEDDING_DIMENSIONS}
            for i in range(len(body["input"]))
        ]
        return httpx.Response(200, json={"data": list(reversed(data))})  # out of order

    vectors = await _endpoint(handler, batch_size=2).embed_documents(["a", "b", "c"])

    assert [v[0] for v in vectors] == [0.0, 1.0, 0.0]  # two batches: [a, b], [c]
    assert len(seen) == 2
    req = seen[0]
    assert req.url == "https://embeddings.eu.example.internal/v1/embeddings"
    assert req.headers["Data-Retention"] == "false"
    assert req.headers["Authorization"] == "Bearer test-only-key"
    assert json.loads(req.content)["dimensions"] == EMBEDDING_DIMENSIONS


async def test_openai_compatible_rejects_wrong_dimensions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 768}]})

    with pytest.raises(EmbeddingError, match="768 dimensions"):
        await _endpoint(handler).embed_query("x")


async def test_openai_compatible_wraps_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(EmbeddingError, match="endpoint failed"):
        await _endpoint(handler).embed_documents(["x"])


# --- local sentence-transformers --------------------------------------------------


class _StubModel:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def encode(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        self.calls.append((texts, kwargs))
        return [[0.5] * EMBEDDING_DIMENSIONS for _ in texts]


async def test_sentence_transformer_uses_e5_prefixes_and_normalisation() -> None:
    stub = _StubModel()
    e = SentenceTransformerEmbedder("intfloat/multilingual-e5-large", model=stub)
    await e.embed_documents(["shenai Gehäuse FERT"])
    await e.embed_query("Edelstahlgehäuse")
    (doc_texts, doc_kwargs), (query_texts, _) = stub.calls
    assert doc_texts == ["passage: shenai Gehäuse FERT"]
    assert query_texts == ["query: Edelstahlgehäuse"]
    assert doc_kwargs["normalize_embeddings"] is True


async def test_sentence_transformer_checks_dimensions() -> None:
    e = SentenceTransformerEmbedder("small-model", model=_StubModel(), dimensions=384)
    with pytest.raises(EmbeddingError, match="1024 dimensions, expected 384"):
        await e.embed_documents(["x"])


# --- settings ----------------------------------------------------------------------


def _settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)


def test_private_endpoint_requires_https_and_eu_attestation() -> None:
    base = {"embedding_provider": "openai_compatible"}
    with pytest.raises(ValidationError, match="EMBEDDING_ENDPOINT_URL is required"):
        _settings(**base)
    with pytest.raises(ValidationError, match="https"):
        _settings(
            **base,
            embedding_endpoint_url="http://embed.example.com",
            embedding_endpoint_eu_attested=True,
        )
    with pytest.raises(ValidationError, match="EU_ATTESTED"):
        _settings(**base, embedding_endpoint_url="https://embed.example.com")
    ok = _settings(
        **base,
        embedding_endpoint_url="https://embed.example.com",
        embedding_endpoint_eu_attested=True,
    )
    assert ok.embedding_endpoint_url
    # plain http only for a local endpoint (e.g. self-hosted TEI) outside production
    assert _settings(
        **base, embedding_endpoint_url="http://localhost:8080", embedding_endpoint_eu_attested=True
    )


def test_hashing_embedder_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="tests only"):
        _settings(
            environment="production",
            auth_mode="oidc",
            embedding_provider="hashing",
            cors_allowed_origins=["https://app.zuschlag.ai"],
        )
