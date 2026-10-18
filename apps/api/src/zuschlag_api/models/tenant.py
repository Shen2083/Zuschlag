from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import String, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from zuschlag_api.db.base import Base, Timestamps


class Tenant(Timestamps, Base):
    """A customer organisation. Its primary key *is* its `tenant_id`, so RLS can
    use the same policy here as on every other table."""

    __tablename__ = "tenants"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # SAP client ("Mandant") and sales area used when building IDocs
    sap_client: Mapped[str | None] = mapped_column(String(3))
    sap_sales_org: Mapped[str | None] = mapped_column(String(4))
    data_region: Mapped[str] = mapped_column(String(32), nullable=False, default="eu-central-1")
    # ALE partner profile for outbound IDocs (validated by sap.reqote.SapOutboundProfile).
    sap_outbound_profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
