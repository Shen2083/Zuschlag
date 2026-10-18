from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Identity,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from zuschlag_api.db.base import Base, TenantScoped, Timestamps, UuidPk


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class QuoteStatus(enum.StrEnum):
    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    SYNCED = "synced"


class QuoteItemKind(enum.StrEnum):
    FINISHED_GOOD = "finished_good"  # SAP MTART FERT
    SEMI_FINISHED = "semi_finished"  # HALB
    RAW_MATERIAL = "raw_material"  # ROH
    PURCHASED_PART = "purchased_part"  # bought-in component (ROH/HAWA)
    LABOR = "labor"  # fabrication operation
    SERVICE = "service"


class MatchStatus(enum.StrEnum):
    MATCHED = "MATCHED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    NOT_APPLICABLE = "NOT_APPLICABLE"  # labor / services: nothing to match


class Sourcing(enum.StrEnum):
    CATALOG = "catalog"  # standard SAP material, confidently matched
    CUSTOM_BUILD = "custom_build"  # finished good built from components
    MISSING_IN_CATALOG = "missing_in_catalog"  # no confident SAP material: create or procure
    INTERNAL = "internal"  # own labor


class Quote(UuidPk, TenantScoped, Timestamps, Base):
    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "quote_number"),
        # Composite FKs: a quote can only reference rows of the same tenant.
        ForeignKeyConstraint(
            ["tenant_id", "rfq_id"], ["rfqs.tenant_id", "rfqs.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("margin_pct >= 0 AND margin_pct < 1000", name="margin_pct_range"),
        CheckConstraint("revision >= 1", name="revision_positive"),
    )

    rfq_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    quote_number: Mapped[str] = mapped_column(String(35), nullable=False)
    status: Mapped[QuoteStatus] = mapped_column(
        _enum(QuoteStatus, "quote_status"), nullable=False, default=QuoteStatus.DRAFT
    )
    # Approval freezes a revision (DB triggers, migration 0005); changes open the next one.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    margin_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    sap_document_number: Mapped[str | None] = mapped_column(String(10))  # VBELN

    # Customer data as extracted from the RFQ (snapshot; customer_id links the master).
    customer_name: Mapped[str | None] = mapped_column(String(200))
    contact_name: Mapped[str | None] = mapped_column(String(200))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    requested_delivery_date: Mapped[date | None] = mapped_column(Date)
    language: Mapped[str | None] = mapped_column(String(8))

    # AI provenance: the validated structured extraction and its compliance hash.
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    llm_model: Mapped[str | None] = mapped_column(String(200))
    llm_compliance_hash: Mapped[str | None] = mapped_column(CHAR(64))
    review_reasons: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Totals (EUR unless `currency` says otherwise).
    material_cost: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    labor_hours: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, server_default="0"
    )
    labor_cost: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    net_total: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )

    # Commercial terms (set by POST /quotes/{id}/calculate)
    payment_terms: Mapped[str | None] = mapped_column(String(4))  # SAP ZTERM, e.g. NT30
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))  # 19.00 | 7.00
    vat_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    gross_total: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, server_default="0"
    )
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Last outbound REQOTE IDoc
    last_idoc_docnum: Mapped[str | None] = mapped_column(CHAR(16))
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[QuoteItem]] = relationship(
        back_populates="quote",
        order_by="(QuoteItem.parent_item_id.nullsfirst(), QuoteItem.position)",
        primaryjoin="and_(Quote.tenant_id == foreign(QuoteItem.tenant_id), "
        "Quote.id == foreign(QuoteItem.quote_id))",
    )


class QuoteItem(UuidPk, TenantScoped, Timestamps, Base):
    """One BOM line. Top-level items (no parent) are what the customer ordered;
    components and labor operations hang below their finished good."""

    __tablename__ = "quote_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint(
            "quote_id", "parent_item_id", "position", postgresql_nulls_not_distinct=True
        ),
        ForeignKeyConstraint(
            ["tenant_id", "quote_id"], ["quotes.tenant_id", "quotes.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_item_id"],
            ["quote_items.tenant_id", "quote_items.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "material_id"],
            ["materials.tenant_id", "materials.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            "match_confidence IS NULL OR (match_confidence >= 0 AND match_confidence <= 1)",
            name="match_confidence_range",
        ),
        CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="unit_cost_non_negative"),
    )

    quote_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    parent_item_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # POSEX for top-level items
    kind: Mapped[QuoteItemKind] = mapped_column(
        _enum(QuoteItemKind, "quote_item_kind"), nullable=False
    )
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    requested_description: Mapped[str | None] = mapped_column(String(1000))  # verbatim from RFQ
    specs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False)  # total for the quote
    quantity_per_parent: Mapped[Decimal | None] = mapped_column(Numeric(15, 3))
    uom: Mapped[str] = mapped_column(String(3), nullable=False)

    # SAP catalog match
    material_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    matnr: Mapped[str | None] = mapped_column(String(40))
    material_type: Mapped[str | None] = mapped_column(String(4))
    match_status: Mapped[MatchStatus] = mapped_column(
        _enum(MatchStatus, "match_status"), nullable=False
    )
    match_confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    match_method: Mapped[str | None] = mapped_column(String(16))
    match_candidates: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    sourcing: Mapped[Sourcing] = mapped_column(_enum(Sourcing, "sourcing"), nullable=False)

    # Costing (per unit of this item; totals for the line)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(15, 4))
    labor_hours: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    labor_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    extended_cost: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    margin_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    unit_margin: Mapped[Decimal | None] = mapped_column(Numeric(15, 4))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(15, 4))
    line_total: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))

    quote: Mapped[Quote] = relationship(
        back_populates="items",
        primaryjoin="and_(Quote.tenant_id == foreign(QuoteItem.tenant_id), "
        "Quote.id == foreign(QuoteItem.quote_id))",
    )


class QuoteAuditTrail(TenantScoped, Base):
    """Append-only history of one quote: AI extraction, matching, pricing,
    human changes. UPDATE/DELETE are blocked by grants and triggers."""

    __tablename__ = "quote_audit_trail"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "quote_id"], ["quotes.tenant_id", "quotes.id"], ondelete="RESTRICT"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    quote_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    timestamp_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
