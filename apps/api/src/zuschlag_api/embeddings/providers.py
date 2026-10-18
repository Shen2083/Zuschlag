"""Embedding backends.

* `SentenceTransformerEmbedder` (default): open-source model run in-process,
  so catalog text never leaves the host. Needs the `embeddings` extra.
* `OpenAICompatibleEmbedder`: a *private* endpoint speaking the OpenAI
  `/embeddings` protocol (Azure OpenAI in an EU region, self-hosted TEI, vLLM).
  Requires https and an explicit EU-hosting attestation.
* `HashingEmbedder`: deterministic, dependency-free feature hashing for tests
  and offline development. Not semantic; refused in production.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import math
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import httpx

from zuschlag_api.core.compliance import MANDATORY_HEADERS
from zuschlag_api.embeddings.base import (
    EMBEDDING_DIMENSIONS,
    Embedder,
    EmbeddingError,
    check_vectors,
)

if TYPE_CHECKING:
    from zuschlag_api.core.config import Settings


class SentenceTransformerEmbedder:
    """Local sentence-transformers model, loaded lazily on first use.

    The default `intfloat/multilingual-e5-large` (MIT licence, 1024 dims) handles
    German and English catalog text; E5 models expect "passage: " / "query: "
    prefixes. Inference runs in a worker thread so the event loop stays free.
    """

    def __init__(
        self,
        model_name: str,
        *,
        dimensions: int = EMBEDDING_DIMENSIONS,
        device: str | None = None,
        document_prefix: str = "passage: ",
        query_prefix: str = "query: ",
        batch_size: int = 32,
        model: Any = None,
    ) -> None:
        if model is None and importlib.util.find_spec("sentence_transformers") is None:
            raise EmbeddingError(
                "EMBEDDING_PROVIDER=sentence_transformers needs the 'embeddings' extra "
                "(uv sync --extra embeddings)"
            )
        self._model_name = model_name
        self._dimensions = dimensions
        self._device = device
        self._document_prefix = document_prefix
        self._query_prefix = query_prefix
        self._batch_size = batch_size
        self._model = model
        self._load_lock = asyncio.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def _get_model(self) -> Any:
        if self._model is None:
            async with self._load_lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    self._model = await asyncio.to_thread(
                        SentenceTransformer, self._model_name, device=self._device
                    )
        return self._model

    async def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = await self._get_model()
        vectors = await asyncio.to_thread(
            model.encode,
            texts,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return check_vectors([list(v) for v in vectors], self._dimensions, len(texts))

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._encode([self._document_prefix + t for t in texts])

    async def embed_query(self, text: str) -> list[float]:
        return (await self._encode([self._query_prefix + text]))[0]


class OpenAICompatibleEmbedder:
    """`POST {base_url}/embeddings` on a private, EU-hosted endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        dimensions: int = EMBEDDING_DIMENSIONS,
        batch_size: int = 128,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = dict(MANDATORY_HEADERS)  # Data-Retention: false
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout, transport=transport
        )
        self._model = model
        self._dimensions = dimensions
        self._batch_size = batch_size

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = list(texts[start : start + self._batch_size])
            try:
                res = await self._client.post(
                    "/embeddings",
                    json={
                        "model": self._model,
                        "input": batch,
                        "dimensions": self._dimensions,
                        "encoding_format": "float",
                    },
                )
                res.raise_for_status()
                data = res.json()["data"]
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                raise EmbeddingError(f"embedding endpoint failed: {exc}") from exc
            ordered = sorted(data, key=lambda d: d["index"])
            out.extend(
                check_vectors([d["embedding"] for d in ordered], self._dimensions, len(batch))
            )
        return out

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed(texts)

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text]))[0]

    async def aclose(self) -> None:
        await self._client.aclose()


_TOKEN = re.compile(r"\w+", re.UNICODE)


class HashingEmbedder:
    """Deterministic bag-of-words + character-trigram feature hashing.

    Similar strings get similar vectors, which is enough for tests and offline
    development. It is not a semantic model.
    """

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self._dimensions = dimensions

    @property
    def model_name(self) -> str:
        return f"hashing-v1-{self._dimensions}"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self._dimensions
        tokens = [t.lower() for t in _TOKEN.findall(text)]
        features = tokens + [t[i : i + 3] for t in tokens for i in range(max(len(t) - 2, 1))]
        for feature in features:
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimensions
            vec[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def embedder_from_settings(settings: Settings) -> Embedder | None:
    """The configured embedder, or None when embeddings are disabled."""
    provider = settings.embedding_provider
    if provider == "disabled":
        return None
    if provider == "hashing":
        return HashingEmbedder()
    if provider == "openai_compatible":
        assert settings.embedding_endpoint_url is not None  # enforced by Settings
        key = settings.embedding_api_key.get_secret_value() if settings.embedding_api_key else None
        return OpenAICompatibleEmbedder(
            base_url=settings.embedding_endpoint_url, model=settings.embedding_model, api_key=key
        )
    return SentenceTransformerEmbedder(settings.embedding_model, device=settings.embedding_device)
