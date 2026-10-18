from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    DateTime,
    Index,
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

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    embedding_model: Mapped[str | None] = mapped_column(String(200))
    # Hash of the exact text that was embedded; unchanged text is never re-embedded.
    embedding_text_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
