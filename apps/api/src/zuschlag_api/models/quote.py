from __future__ import annotations

import enum
import uuid
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from zuschlag_api.db.base import Base, TenantScoped, Timestamps, UuidPk


class QuoteStatus(enum.StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SYNCED = "synced"


class LineItemType(enum.StrEnum):
    MATERIAL = "material"
    PART = "part"
    LABOR = "labor"


class Quote(UuidPk, TenantScoped, Timestamps, Base):
    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "quote_number"),
        # Composite FK: a quote can only reference an RFQ of the same tenant.
        ForeignKeyConstraint(
            ["tenant_id", "rfq_id"], ["rfqs.tenant_id", "rfqs.id"], ondelete="RESTRICT"
        ),
        CheckConstraint("margin_pct >= 0 AND margin_pct < 1000", name="margin_pct_range"),
    )

    rfq_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    quote_number: Mapped[str] = mapped_column(String(35), nullable=False)
    status: Mapped[QuoteStatus] = mapped_column(
        Enum(QuoteStatus, name="quote_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=QuoteStatus.DRAFT,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    margin_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    sap_document_number: Mapped[str | None] = mapped_column(String(10))  # VBELN

    line_items: Mapped[list[QuoteLineItem]] = relationship(
        back_populates="quote",
        order_by="QuoteLineItem.position",
        primaryjoin="and_(Quote.tenant_id == foreign(QuoteLineItem.tenant_id), "
        "Quote.id == foreign(QuoteLineItem.quote_id))",
    )


class QuoteLineItem(UuidPk, TenantScoped, Timestamps, Base):
    __tablename__ = "quote_line_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("quote_id", "position"),
        ForeignKeyConstraint(
            ["tenant_id", "quote_id"], ["quotes.tenant_id", "quotes.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "material_id"],
            ["materials.tenant_id", "materials.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint(
            "ai_confidence IS NULL OR (ai_confidence >= 0 AND ai_confidence <= 1)",
            name="ai_confidence_range",
        ),
    )

    quote_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # POSEX
    item_type: Mapped[LineItemType] = mapped_column(
        Enum(LineItemType, name="line_item_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    material_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False)
    uom: Mapped[str] = mapped_column(String(3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    ai_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))

    quote: Mapped[Quote] = relationship(
        back_populates="line_items",
        primaryjoin="and_(Quote.tenant_id == foreign(QuoteLineItem.tenant_id), "
        "Quote.id == foreign(QuoteLineItem.quote_id))",
    )
