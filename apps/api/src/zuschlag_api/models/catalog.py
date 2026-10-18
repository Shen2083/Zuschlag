from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from zuschlag_api.db.base import Base, TenantScoped, Timestamps, UuidPk
from zuschlag_api.embeddings.base import EMBEDDING_DIMENSIONS


class SapSourced:
    """Provenance used for idempotent, order-safe upserts from SAP IDocs."""

    source_system: Mapped[str | None] = mapped_column(String(10))  # EDI_DC40-SNDPRN
    source_docnum: Mapped[int | None] = mapped_column(BigInteger)  # EDI_DC40-DOCNUM
    content_sha256: Mapped[str | None] = mapped_column(CHAR(64))


class Material(UuidPk, TenantScoped, SapSourced, Timestamps, Base):
    """A row of the tenant's SAP material master (MARA/MAKT), mirrored for
    semantic matching of free-text RFQ lines."""

    __tablename__ = "materials"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "matnr"),
        Index(
            "ix_materials_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # pg_trgm index for lexical (fuzzy) matching on MATNR + short texts.
        Index(
            "ix_materials_search_text_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
    )

    matnr: Mapped[str] = mapped_column(String(40), nullable=False)  # S/4HANA: 40 chars
    material_type: Mapped[str | None] = mapped_column(String(4))  # MTART
    material_group: Mapped[str | None] = mapped_column(String(9))  # MATKL
    base_uom: Mapped[str] = mapped_column(String(3), nullable=False)  # MEINS
    gross_weight: Mapped[Decimal | None] = mapped_column(Numeric(13, 3))  # BRGEW
    net_weight: Mapped[Decimal | None] = mapped_column(Numeric(13, 3))  # NTGEW
    weight_unit: Mapped[str | None] = mapped_column(String(3))  # GEWEI
    # Primary short text (preferred language) and all E1MAKTM texts by ISO language.
    description: Mapped[str | None] = mapped_column(String(200))
    descriptions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    long_text: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Costing price from MBEW (E1MBEWM): price per `price_unit` base units.
    standard_price: Mapped[Decimal | None] = mapped_column(Numeric(15, 4))
    price_unit: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    price_currency: Mapped[str | None] = mapped_column(String(3))
    price_valuation_area: Mapped[str | None] = mapped_column(String(4))  # BWKEY

    # Lower-cased MATNR + short texts, maintained by PostgreSQL for trigram search.
    search_text: Mapped[str] = mapped_column(
        Text,
        Computed(
            "lower(matnr || ' ' || coalesce(description, '') || ' ' || "
            "coalesce(descriptions ->> 'DE', '') || ' ' || coalesce(descriptions ->> 'EN', ''))",
            persisted=True,
        ),
    )

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    embedding_model: Mapped[str | None] = mapped_column(String(200))
    # Hash of the exact text that was embedded; unchanged text is never re-embedded.
    embedding_text_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
