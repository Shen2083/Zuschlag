from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

# Must match the pgvector column (materials.embedding VECTOR(1024)).
EMBEDDING_DIMENSIONS = 1024


class EmbeddingError(RuntimeError):
    """The embedding backend failed or returned unusable vectors."""


class Embedder(Protocol):
    """Turns text into L2-normalised vectors of `dimensions` floats.

    Documents (catalog entries) and queries (RFQ lines) are embedded through
    separate methods because retrieval models such as E5 expect different
    prefixes for each.
    """

    @property
    def model_name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


def check_vectors(
    vectors: Sequence[Sequence[float]], expected: int, count: int
) -> list[list[float]]:
    if len(vectors) != count:
        raise EmbeddingError(f"backend returned {len(vectors)} vectors for {count} texts")
    out: list[list[float]] = []
    for v in vectors:
        if len(v) != expected:
            raise EmbeddingError(f"backend returned {len(v)} dimensions, expected {expected}")
        out.append([float(x) for x in v])
    return out
