from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from zuschlag_api.db.base import Base, TenantScoped, UuidPk


class SapIdocReceipt(UuidPk, TenantScoped, Base):
    """One row per IDoc ever accepted. `(tenant, sender, docnum)` is unique, so
    a re-delivered IDoc is recognised and acknowledged without being applied
    twice; a *different* payload under a known DOCNUM is rejected as a conflict."""

    __tablename__ = "sap_idoc_receipts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "sender", "docnum"),
    )

    sender: Mapped[str] = mapped_column(String(10), nullable=False)  # SNDPRN
    docnum: Mapped[str] = mapped_column(CHAR(16), nullable=False)  # zero-padded DOCNUM
    idoc_type: Mapped[str] = mapped_column(String(30), nullable=False)  # IDOCTYP
    message_type: Mapped[str] = mapped_column(String(30), nullable=False)  # MESTYP
    object_key: Mapped[str] = mapped_column(String(40), nullable=False)  # MATNR / KUNNR
    content_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    object_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
