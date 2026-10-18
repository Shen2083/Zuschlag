"""Hybrid matcher against a seeded SAP catalog in PostgreSQL (pgvector + pg_trgm)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.rfq_support import ConceptEmbedder, seed_catalog
from zuschlag_api.db.session import tenant_session
from zuschlag_api.models import MatchStatus, Material
from zuschlag_api.rfq.matching import HybridMatcher, MatchConfig

pytestmark = pytest.mark.integration

# The concept embedder spans the full cosine range, so no calibration offset.
CONFIG = MatchConfig(dense_floor=0.0, dense_ceiling=1.0)


@pytest.fixture
async def catalog_session(
    sessionmaker: async_sessionmaker[AsyncSession], tenant_a: uuid.UUID
) -> AsyncIterator[tuple[AsyncSession, ConceptEmbedder]]:
    embedder = ConceptEmbedder()
    async with tenant_session(tenant_a, sessionmaker=sessionmaker) as s:
        await seed_catalog(s, embedder)
        yield s, embedder


async def test_cited_material_number_is_an_exact_match(
    catalog_session: tuple[AsyncSession, ConceptEmbedder],
) -> None:
    s, emb = catalog_session
    r = await HybridMatcher(s, emb, CONFIG).match(
        description="40 Stück Schwerlastrollen",
        search_text="Schwerlastrolle",
        kind="purchased_part",
        unit="PCE",
        material_number="pt-cas-125hd",  # case-insensitive
    )
    assert (r.method, r.status, r.confidence) == ("exact", MatchStatus.MATCHED, 1.0)
    assert r.best is not None
    assert r.best.matnr == "PT-CAS-125HD"
    assert emb.queries == []  # exact hit: no embedding needed


async def test_material_number_in_free_text(
    catalog_session: tuple[AsyncSession, ConceptEmbedder],
) -> None:
    s, emb = catalog_session
    r = await HybridMatcher(s, emb, CONFIG).match(
        description="Ersatz für RM-1430-SH20, gleiche Qualität",
        search_text="Edelstahlblech",
        kind="raw_material",
        unit="PCE",
    )
    assert r.method == "exact"
    assert r.confidence == 0.95
    assert r.best is not None
    assert r.best.matnr == "RM-1430-SH20"


async def test_hybrid_match_across_languages(
    catalog_session: tuple[AsyncSession, ConceptEmbedder],
) -> None:
    s, emb = catalog_session
    r = await HybridMatcher(s, emb, CONFIG).match(
        description="Heavy-duty castor with brake, 125 mm",
        search_text="Schwerlastrolle 125 mm Bremse heavy-duty castor brake",
        kind="purchased_part",
        unit="PCE",
    )
    assert r.method == "hybrid"
    assert r.status is MatchStatus.MATCHED
    assert r.best is not None
    assert r.best.matnr == "PT-CAS-125HD"
    assert r.best.dense_similarity is not None
    assert r.best.lexical_similarity > 0.3
    assert 0.75 <= r.confidence <= 1.0
    assert len(r.candidates) <= 3


async def test_lexical_only_without_embedder(
    catalog_session: tuple[AsyncSession, ConceptEmbedder],
) -> None:
    s, _ = catalog_session
    r = await HybridMatcher(s, None, CONFIG).match(
        description="Edelstahl-Arbeitstisch 1200 x 700",
        search_text="edelstahl-arbeitstisch 1200 x 700 mm",
        kind="finished_good",
        unit="PCE",
    )
    assert r.method == "lexical"
    assert r.best is not None
    assert r.best.matnr == "FG-WT-1200"
    assert r.best.dense_similarity is None


async def test_unknown_material_needs_human_review(
    catalog_session: tuple[AsyncSession, ConceptEmbedder],
) -> None:
    s, emb = catalog_session
    r = await HybridMatcher(s, emb, CONFIG).match(
        description="Lochblech 1.4301, 1,5 mm, Rundloch R5T8",
        search_text="Lochblech 1.4301 1,5 mm R5T8 perforated stainless sheet",
        kind="raw_material",
        unit="KGM",
    )
    assert r.status is MatchStatus.NEEDS_HUMAN_REVIEW
    assert r.confidence < 0.75
    assert "uom_mismatch" in r.flags


async def test_wrong_material_type_is_penalised(
    catalog_session: tuple[AsyncSession, ConceptEmbedder],
) -> None:
    s, emb = catalog_session
    m = HybridMatcher(s, emb, CONFIG)
    query = {
        "description": "Edelstahl-Arbeitstisch 1200 x 700 mm",
        "search_text": "Edelstahl-Arbeitstisch 1200 x 700 mm work table",
        "unit": "PCE",
    }
    as_fert = await m.match(kind="finished_good", **query)
    as_raw = await m.match(kind="raw_material", **query)  # a table is not a ROH material
    assert as_fert.best is not None
    assert as_raw.best is not None
    assert as_fert.best.matnr == as_raw.best.matnr == "FG-WT-1200"
    assert "type_mismatch" in as_raw.flags
    assert as_raw.confidence < as_fert.confidence


async def test_close_runner_up_is_flagged_ambiguous(
    catalog_session: tuple[AsyncSession, ConceptEmbedder],
) -> None:
    s, emb = catalog_session
    # A second variant of the same castor that differs only in a detail the RFQ
    # does not mention (zinc-plated): the matcher cannot know which one is meant.
    text = "PT-CAS-125ZN Schwerlast-Lenkrolle Ø125 mm, 150 kg, mit Bremse, verzinkt HAWA"
    [vector] = await emb.embed_documents([text])
    s.add(
        Material(
            matnr="PT-CAS-125ZN",
            material_type="HAWA",
            base_uom="PCE",
            description="Schwerlast-Lenkrolle Ø125 mm, 150 kg, mit Bremse, verzinkt",
            embedding=vector,
        )
    )
    await s.flush()
    r = await HybridMatcher(s, emb, CONFIG).match(
        description="Schwerlast-Lenkrolle 125 mm, 150 kg mit Bremse",
        search_text="Schwerlast-Lenkrolle 125 mm 150 kg Bremse heavy-duty castor brake",
        kind="purchased_part",
        unit="PCE",
    )
    assert {c.matnr for c in r.candidates[:2]} == {"PT-CAS-125HD", "PT-CAS-125ZN"}
    assert "ambiguous" in r.flags
    assert r.status is MatchStatus.NEEDS_HUMAN_REVIEW


async def test_other_tenants_catalog_is_invisible(
    sessionmaker: async_sessionmaker[AsyncSession], tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    emb = ConceptEmbedder()
    async with tenant_session(tenant_a, sessionmaker=sessionmaker) as s:
        await seed_catalog(s, emb)
    async with tenant_session(tenant_b, sessionmaker=sessionmaker) as s:
        r = await HybridMatcher(s, emb, CONFIG).match(
            description="x",
            search_text="Schwerlastrolle",
            kind="purchased_part",
            unit="PCE",
            material_number="PT-CAS-125HD",
        )
    assert r.best is None
    assert r.flags == ["no_candidates"]


async def test_verbatim_sap_short_text_is_an_exact_match(
    catalog_session: tuple[AsyncSession, ConceptEmbedder],
) -> None:
    s, emb = catalog_session
    r = await HybridMatcher(s, emb, CONFIG).match(
        description="  scharnier   EDELSTAHL, 180° öffnung ",  # case and spacing ignored
        search_text="hinge stainless",
        kind="purchased_part",
        unit="PCE",
    )
    assert (r.method, r.status, r.confidence) == ("exact_text", MatchStatus.MATCHED, 0.97)
    assert r.best is not None
    assert r.best.matnr == "PT-HNG-SS180"
    assert emb.queries == []


async def test_short_text_shared_by_two_materials_needs_review(
    catalog_session: tuple[AsyncSession, ConceptEmbedder],
) -> None:
    s, emb = catalog_session
    s.add(
        Material(
            matnr="PT-HNG-SS180B",
            material_type="HAWA",
            base_uom="PCE",
            description="Scharnier Edelstahl, 180° Öffnung",
            descriptions={},
        )
    )
    await s.flush()
    r = await HybridMatcher(s, emb, CONFIG).match(
        description="Scharnier Edelstahl, 180° Öffnung",
        search_text="Scharnier",
        kind="purchased_part",
        unit="PCE",
    )
    assert r.method == "exact_text"
    assert "ambiguous" in r.flags
    assert r.status is MatchStatus.NEEDS_HUMAN_REVIEW


async def test_partial_text_is_not_an_exact_text_match(
    catalog_session: tuple[AsyncSession, ConceptEmbedder],
) -> None:
    s, emb = catalog_session
    r = await HybridMatcher(s, emb, CONFIG).match(
        description="Scharnier Edelstahl",  # only a prefix of the MAKTX
        search_text="Scharnier Edelstahl hinge stainless",
        kind="purchased_part",
        unit="PCE",
    )
    assert r.method == "hybrid"
