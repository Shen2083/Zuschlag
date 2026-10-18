"""Shared test support for the RFQ -> quote pipeline."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from zuschlag_api.embeddings import HashingEmbedder
from zuschlag_api.models import Material

RFQ_FIXTURES = Path(__file__).parent / "fixtures" / "rfq"


def rfq_text(name: str) -> str:
    return (RFQ_FIXTURES / f"{name}.txt").read_text(encoding="utf-8")


def golden_extraction(name: str) -> dict[str, Any]:
    """The structured output the LLM is expected to produce for fixture `name`."""
    data: dict[str, Any] = json.loads(
        (RFQ_FIXTURES / f"{name}.extraction.json").read_text(encoding="utf-8")
    )
    return data


# Bilingual synonym groups: texts that share a concept get similar vectors, the
# way a multilingual embedding model would place them.
CONCEPTS: list[tuple[str, ...]] = [
    ("rack", "racks", "serverschrank", "server", "schrank", "cabinet"),
    ("rolle", "rollen", "lenkrolle", "bockrolle", "schwerlastrolle", "castor", "caster", "castors"),
    ("blech", "sheet", "edelstahlblech"),
    ("lochblech", "perforated"),
    ("rohr", "vierkantrohr", "tube", "profil"),
    ("scharnier", "hinge", "scharniere"),
    ("lüfter", "axiallüfter", "fan", "ventilator"),
    ("edelstahl", "stainless", "1.4301", "inox"),
    ("tisch", "arbeitstisch", "table", "workbench"),
    ("bremse", "brake"),
    ("lackiert", "painted", "stahlblech"),
]
_WORD = re.compile(r"[\wäöüß.]+", re.UNICODE)


class ConceptEmbedder(HashingEmbedder):
    """Concept dimensions (strong) + feature hashing (weak), L2-normalised."""

    def __init__(self) -> None:
        super().__init__()
        self.queries: list[str] = []
        self._index = {word: i for i, group in enumerate(CONCEPTS) for word in group}

    def _vector(self, text: str) -> list[float]:
        vec = [0.15 * x for x in super()._vector(text)]
        for token in _WORD.findall(text.lower()):
            for part in re.split(r"[-]", token):
                if part in self._index:
                    vec[self.dimensions - 1 - self._index[part]] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return await super().embed_query(text)


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    matnr: str
    description: str
    material_type: str
    base_uom: str
    price: Decimal | None
    price_unit: int = 1


CATALOG: Sequence[CatalogEntry] = (
    CatalogEntry(
        "RM-1430-SH20",
        "Edelstahlblech 1.4301, 2,0 mm, 2000 x 1000",
        "ROH",
        "PCE",
        Decimal("148.50"),
    ),
    CatalogEntry(
        "RM-1430-TQ40",
        "Vierkantrohr Edelstahl 1.4301, 40 x 40 x 3 mm, 6 m",
        "ROH",
        "PCE",
        Decimal("96.20"),
    ),
    # priced per 10 pieces (PEINH = 10)
    CatalogEntry(
        "PT-CAS-125HD",
        "Schwerlast-Lenkrolle Ø125 mm, 150 kg, mit Bremse",
        "HAWA",
        "PCE",
        Decimal("389.00"),
        10,
    ),
    CatalogEntry(
        "PT-HNG-SS180", "Scharnier Edelstahl, 180° Öffnung", "HAWA", "PCE", Decimal("12.40")
    ),
    CatalogEntry("PT-FAN-EC120", "EC-Axiallüfter 120 mm, 230 V", "HAWA", "PCE", Decimal("27.80")),
    CatalogEntry(
        "FG-RACK-42U", "Serverschrank 42 HE, Stahlblech lackiert", "FERT", "PCE", Decimal("1180.00")
    ),
    CatalogEntry(
        "FG-WT-1200", "Edelstahl-Arbeitstisch 1200 x 700 mm", "FERT", "PCE", Decimal("640.00")
    ),
    CatalogEntry("RM-SEAL-EPDM", "EPDM-Dichtprofil 10 x 8 mm", "ROH", "MTR", None),
)


async def seed_catalog(session: AsyncSession, embedder: HashingEmbedder) -> dict[str, Material]:
    vectors = await embedder.embed_documents(
        [f"{e.matnr} {e.description} {e.material_type}" for e in CATALOG]
    )
    rows: dict[str, Material] = {}
    for entry, vector in zip(CATALOG, vectors, strict=True):
        m = Material(
            matnr=entry.matnr,
            material_type=entry.material_type,
            base_uom=entry.base_uom,
            description=entry.description,
            descriptions={"DE": entry.description},
            standard_price=entry.price,
            price_unit=entry.price_unit,
            price_currency="EUR" if entry.price is not None else None,
            embedding=vector,
            embedding_model=embedder.model_name,
        )
        session.add(m)
        rows[entry.matnr] = m
    await session.flush()
    return rows
