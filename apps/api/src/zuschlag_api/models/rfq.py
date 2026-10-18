from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from zuschlag_api.db.base import Base, TenantScoped, Timestamps, UuidPk


class RfqSource(enum.StrEnum):
    EMAIL = "email"
    PDF = "pdf"
    MANUAL = "manual"


class RfqStatus(enum.StrEnum):
    RECEIVED = "received"
    PARSED = "parsed"
    QUOTED = "quoted"
    REJECTED = "rejected"


class Rfq(UuidPk, TenantScoped, Timestamps, Base):
    """An inbound, unstructured customer request for quotation."""

    __tablename__ = "rfqs"
    __table_args__ = (UniqueConstraint("tenant_id", "id"),)

    source: Mapped[RfqSource] = mapped_column(
        Enum(RfqSource, name="rfq_source", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    status: Mapped[RfqStatus] = mapped_column(
        Enum(RfqStatus, name="rfq_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=RfqStatus.RECEIVED,
    )
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    customer_ref: Mapped[str | None] = mapped_column(String(35))  # SAP BSTKD length
    body_text: Mapped[str | None] = mapped_column(Text)
    # Original e-mail / PDF lives in object storage (EU bucket), not in the DB.
    attachment_object_key: Mapped[str | None] = mapped_column(String(512))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
