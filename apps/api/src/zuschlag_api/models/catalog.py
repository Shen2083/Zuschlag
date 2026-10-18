from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from zuschlag_api.db.base import Base, TenantScoped, Timestamps, UuidPk

EMBEDDING_DIMENSIONS = 1024


class Material(UuidPk, TenantScoped, Timestamps, Base):
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
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    long_text: Mapped[str | None] = mapped_column(Text)
    base_uom: Mapped[str] = mapped_column(String(3), nullable=False)  # ISO unit, e.g. PCE
    material_group: Mapped[str | None] = mapped_column(String(9))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
