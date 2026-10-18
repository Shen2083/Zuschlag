from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, BigInteger, DateTime, Identity, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from zuschlag_api.db.base import Base, TenantScoped


class AuditLog(TenantScoped, Base):
    """Append-only, tamper-evident audit trail (GoBD).

    Immutability is enforced by the database, not by this class:
      * the runtime role has only SELECT/INSERT on the table,
      * triggers reject every UPDATE, DELETE and TRUNCATE (even for the owner),
      * a BEFORE INSERT trigger stamps `timestamp_utc`, assigns a gap-free
        per-tenant `seq` and links each row to its predecessor with a SHA-256
        hash chain (`prev_hash` -> `entry_hash`), so any out-of-band change is
        detectable with `app.audit_chain_breaks(tenant_id)`.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (UniqueConstraint("tenant_id", "seq"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    # Set by the database trigger; any client-supplied value is overwritten.
    timestamp_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # HMAC-SHA256 of the client IP (keyed, so it can't be brute-forced from the
    # 2^32 IPv4 space). NULL for system actions without a client.
    ip_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    # Small, non-personal context only (ids, counts, hashes) — never prompt text.
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    seq: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    prev_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, server_default="")
    entry_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, server_default="")
