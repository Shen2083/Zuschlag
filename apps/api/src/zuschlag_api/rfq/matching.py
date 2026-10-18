"""Hybrid matching of RFQ lines against the tenant's SAP material master.

Three signals, cheapest and most certain first:

1. **Exact SAP match**: a material number cited in the RFQ (or a token in the
   text) that equals a MATNR (confidence ~1.0), or a requested description that
   is word for word a material's SAP short text (MAKTX, any language).
2. **Dense similarity**: pgvector cosine similarity between the query
   embedding and the material embedding (HNSW index).
3. **Lexical similarity**: pg_trgm `word_similarity` between the search phrase
   and MATNR + short texts (GIN trigram index). Catches article numbers,
   grades and dimensions that embeddings blur.

Raw scores are calibrated to 0..1 (embedding models and trigram scores each
occupy a narrow band of their nominal range), fused, then adjusted for
material-type fit (FERT/HALB/ROH), unit fit and ambiguity between the top two
candidates. Below the review threshold an item is NEEDS_HUMAN_REVIEW.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from zuschlag_api.db.session import TENANT_KEY
from zuschlag_api.embeddings.base import EMBEDDING_DIMENSIONS, Embedder
from zuschlag_api.models import MatchStatus

# Which SAP material types (MTART) fit which kind of requested item.
EXPECTED_MATERIAL_TYPES: dict[str, frozenset[str]] = {
    "finished_good": frozenset({"FERT"}),
    "semi_finished": frozenset({"HALB"}),
    "raw_material": frozenset({"ROH"}),
    "purchased_part": frozenset({"ROH", "HAWA", "NLAG", "HALB"}),
    "service": frozenset({"DIEN"}),
}

# Flags that always require a human decision, whatever the confidence.
REVIEW_FLAGS = frozenset({"ambiguous", "multiple_exact_numbers"})

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{3,39}")


@dataclass(frozen=True, slots=True)
class MatchConfig:
    review_threshold: float = 0.75
    # Calibration: raw score at or below `floor` -> 0, at or above `ceiling` -> 1.
    # Defaults suit intfloat/multilingual-e5-large and German short texts;
    # re-calibrate on a labelled sample of your own catalog.
    dense_floor: float = 0.70
    dense_ceiling: float = 0.95
    lexical_floor: float = 0.10
    lexical_ceiling: float = 0.60
    dense_weight: float = 0.6
    lexical_weight: float = 0.4
    candidates_per_signal: int = 20
    lexical_retrieval_threshold: float = 0.3
    type_mismatch_factor: float = 0.85
    uom_mismatch_factor: float = 0.95
    ambiguity_margin: float = 0.05
    ambiguity_factor: float = 0.9
    exact_cited_confidence: float = 1.0
    exact_token_confidence: float = 0.95
    exact_text_confidence: float = 0.97


@dataclass(frozen=True, slots=True)
class Candidate:
    material_id: uuid.UUID
    matnr: str
    description: str | None
    material_type: str | None
    base_uom: str
    standard_price: Decimal | None
    price_unit: int
    price_currency: str | None
    dense_similarity: float | None
    lexical_similarity: float
    score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "material_id": str(self.material_id),
            "matnr": self.matnr,
            "description": self.description,
            "material_type": self.material_type,
            "base_uom": self.base_uom,
            "dense_similarity": None
            if self.dense_similarity is None
            else round(self.dense_similarity, 4),
            "lexical_similarity": round(self.lexical_similarity, 4),
            "score": round(self.score, 4),
        }


@dataclass(frozen=True, slots=True)
class MatchResult:
    status: MatchStatus
    confidence: float
    method: str  # exact | hybrid | lexical | none
    best: Candidate | None
    candidates: list[Candidate] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return self.status is MatchStatus.NEEDS_HUMAN_REVIEW


def _calibrate(value: float, floor: float, ceiling: float) -> float:
    if ceiling <= floor:
        return 1.0 if value >= ceiling else 0.0
    return min(1.0, max(0.0, (value - floor) / (ceiling - floor)))


_COLUMNS = """
    m.id, m.matnr, m.description, m.material_type, m.base_uom,
    m.standard_price, m.price_unit, m.price_currency
"""

# Only the constant column list is interpolated; every value is a bound parameter.
_EXACT_SQL = text(
    f"SELECT {_COLUMNS} FROM materials m "  # noqa: S608
    "WHERE m.tenant_id = :tenant AND m.is_active AND upper(m.matnr) = ANY(:tokens)"
)

# Requested description == SAP short text (MAKTX in any language), case and spacing ignored.
_NORMALIZED = "regexp_replace(lower(btrim({})), '\\s+', ' ', 'g')"
_EXACT_TEXT_SQL = text(
    f"""
    SELECT {_COLUMNS} FROM materials m
     WHERE m.tenant_id = :tenant AND m.is_active
       AND ({_NORMALIZED.format("m.description")} = :t
            OR EXISTS (SELECT 1 FROM jsonb_each_text(m.descriptions) d
                        WHERE {_NORMALIZED.format("d.value")} = :t))
     ORDER BY m.matnr
     LIMIT 3
    """  # noqa: S608
)

_LEXICAL_ONLY_SQL = text(
    f"""
    SELECT {_COLUMNS}, NULL::float8 AS dense_sim, word_similarity(:q, m.search_text) AS lex_sim
      FROM materials m
     WHERE m.tenant_id = :tenant AND m.is_active AND :q <% m.search_text
     ORDER BY lex_sim DESC
     LIMIT :k
    """  # noqa: S608
)

_HYBRID_SQL = text(
    f"""
    WITH dense AS (
        SELECT m.id, 1 - (m.embedding <=> :qvec) AS dense_sim
          FROM materials m
         WHERE m.tenant_id = :tenant AND m.is_active AND m.embedding IS NOT NULL
         ORDER BY m.embedding <=> :qvec
         LIMIT :k
    ), lexical AS (
        SELECT m.id
          FROM materials m
         WHERE m.tenant_id = :tenant AND m.is_active AND :q <% m.search_text
         ORDER BY word_similarity(:q, m.search_text) DESC
         LIMIT :k
    ), pool AS (
        SELECT id FROM dense UNION SELECT id FROM lexical
    )
    SELECT {_COLUMNS},
           CASE WHEN m.embedding IS NULL THEN NULL
                ELSE 1 - (m.embedding <=> :qvec) END AS dense_sim,
           word_similarity(:q, m.search_text) AS lex_sim
      FROM pool JOIN materials m ON m.id = pool.id
    """  # noqa: S608
).bindparams(bindparam("qvec", type_=Vector(EMBEDDING_DIMENSIONS)))


class HybridMatcher:
    def __init__(
        self, session: AsyncSession, embedder: Embedder | None, config: MatchConfig | None = None
    ) -> None:
        self._session = session
        self._embedder = embedder
        self.config = config or MatchConfig()
        self._tuned = False

    @property
    def _tenant(self) -> uuid.UUID:
        return self._session.info[TENANT_KEY]  # type: ignore[no-any-return]

    async def _tune_session(self) -> None:
        """Per-transaction pgvector/pg_trgm settings (all SET LOCAL)."""
        if self._tuned:
            return
        s = self._session
        await s.execute(
            text("SELECT set_config('pg_trgm.word_similarity_threshold', :t, true)"),
            {"t": str(self.config.lexical_retrieval_threshold)},
        )
        await s.execute(text("SELECT set_config('hnsw.ef_search', '100', true)"))
        version = await s.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        if version and tuple(int(p) for p in version.split(".")[:2]) >= (0, 8):
            # Keep scanning the graph until enough rows survive the tenant filter.
            await s.execute(text("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true)"))
        self._tuned = True

    async def match(
        self,
        *,
        description: str,
        search_text: str,
        kind: str,
        unit: str,
        material_number: str | None = None,
    ) -> MatchResult:
        await self._tune_session()
        exact = await self._exact(description, search_text, kind, unit, material_number)
        if exact is None:
            exact = await self._exact_text(description, kind, unit)
        if exact is not None:
            return exact

        query = (search_text or description).lower()
        qvec = (
            await self._embedder.embed_query(search_text or description) if self._embedder else None
        )
        if qvec is not None:
            rows = await self._session.execute(
                _HYBRID_SQL,
                {
                    "tenant": self._tenant,
                    "q": query,
                    "qvec": qvec,
                    "k": self.config.candidates_per_signal,
                },
            )
        else:
            rows = await self._session.execute(
                _LEXICAL_ONLY_SQL,
                {"tenant": self._tenant, "q": query, "k": self.config.candidates_per_signal},
            )
        candidates = sorted(
            (self._score(r, kind, unit) for r in rows), key=lambda c: c[0].score, reverse=True
        )
        if not candidates:
            return MatchResult(
                MatchStatus.NEEDS_HUMAN_REVIEW, 0.0, "none", None, [], ["no_candidates"]
            )

        (best, flags), *rest = candidates
        confidence = best.score
        if rest and best.score - rest[0][0].score < self.config.ambiguity_margin:
            confidence *= self.config.ambiguity_factor
            flags = [*flags, "ambiguous"]
        method = "hybrid" if best.dense_similarity is not None else "lexical"
        return self._result(confidence, method, best, [c for c, _ in candidates[:3]], flags)

    def _result(
        self,
        confidence: float,
        method: str,
        best: Candidate,
        top: list[Candidate],
        flags: list[str],
    ) -> MatchResult:
        confidence = round(min(1.0, max(0.0, confidence)), 2)
        # Two equally good SAP materials cannot be resolved by a score: a person decides.
        forced_review = bool(REVIEW_FLAGS.intersection(flags))
        status = (
            MatchStatus.MATCHED
            if confidence >= self.config.review_threshold and not forced_review
            else MatchStatus.NEEDS_HUMAN_REVIEW
        )
        return MatchResult(status, confidence, method, best, top, flags)

    def _fit(
        self, kind: str, unit: str, material_type: str | None, base_uom: str
    ) -> tuple[float, list[str]]:
        factor, flags = 1.0, []
        expected = EXPECTED_MATERIAL_TYPES.get(kind)
        if expected and material_type and material_type not in expected:
            factor *= self.config.type_mismatch_factor
            flags.append("type_mismatch")
        if unit and base_uom and unit != base_uom:
            factor *= self.config.uom_mismatch_factor
            flags.append("uom_mismatch")
        return factor, flags

    def _score(self, row: Any, kind: str, unit: str) -> tuple[Candidate, list[str]]:
        c = self.config
        lexical = _calibrate(float(row.lex_sim or 0.0), c.lexical_floor, c.lexical_ceiling)
        if row.dense_sim is None:
            fused = lexical
        else:
            dense = _calibrate(float(row.dense_sim), c.dense_floor, c.dense_ceiling)
            fused = c.dense_weight * dense + c.lexical_weight * lexical
        factor, flags = self._fit(kind, unit, row.material_type, row.base_uom)
        return self._candidate(row, row.dense_sim, float(row.lex_sim or 0.0), fused * factor), flags

    @staticmethod
    def _candidate(row: Any, dense: float | None, lexical: float, score: float) -> Candidate:
        return Candidate(
            material_id=row.id,
            matnr=row.matnr,
            description=row.description,
            material_type=row.material_type,
            base_uom=row.base_uom,
            standard_price=row.standard_price,
            price_unit=row.price_unit,
            price_currency=row.price_currency,
            dense_similarity=None if dense is None else float(dense),
            lexical_similarity=lexical,
            score=score,
        )

    async def _exact(
        self, description: str, search_text: str, kind: str, unit: str, material_number: str | None
    ) -> MatchResult | None:
        cited = material_number.strip().upper() if material_number else None
        tokens = {
            t.upper()
            for t in _TOKEN.findall(f"{description} {search_text}")
            if any(ch.isdigit() for ch in t)
        }
        if cited:
            tokens.add(cited)
        if not tokens:
            return None
        rows = list(
            await self._session.execute(
                _EXACT_SQL, {"tenant": self._tenant, "tokens": sorted(tokens)}
            )
        )
        if not rows:
            return None
        # Prefer the explicitly cited number, then the longest (most specific) token.
        rows.sort(key=lambda r: (r.matnr.upper() != cited, -len(r.matnr)))
        row = rows[0]
        base = (
            self.config.exact_cited_confidence
            if row.matnr.upper() == cited
            else self.config.exact_token_confidence
        )
        factor, flags = self._fit(kind, unit, row.material_type, row.base_uom)
        best = self._candidate(row, None, 1.0, base * factor)
        if len(rows) > 1:
            flags = [*flags, "multiple_exact_numbers"]
        others = [self._candidate(r, None, 1.0, base * factor) for r in rows[1:3]]
        return self._result(best.score, "exact", best, [best, *others], flags)

    async def _exact_text(self, description: str, kind: str, unit: str) -> MatchResult | None:
        """The customer used the SAP short text verbatim (e.g. copied from our catalog)."""
        normalized = " ".join(description.lower().split())
        if len(normalized) < 8:  # "Schraube" alone is not an identification
            return None
        rows = list(
            await self._session.execute(_EXACT_TEXT_SQL, {"tenant": self._tenant, "t": normalized})
        )
        if not rows:
            return None
        factor, flags = self._fit(kind, unit, rows[0].material_type, rows[0].base_uom)
        score = self.config.exact_text_confidence * factor
        top = [self._candidate(r, None, 1.0, score) for r in rows]
        if len(rows) > 1:
            flags = [*flags, "ambiguous"]  # two materials share the text: a person decides
        return self._result(score, "exact_text", top[0], top, flags)
