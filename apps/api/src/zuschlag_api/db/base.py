"""Declarative base and the tenancy mixin every domain table uses."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, Uuid, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TenantScoped:
    """Adds a mandatory `tenant_id` and marks the model for the tenancy guards.

    Isolation is enforced in three independent layers:
      1. PostgreSQL row-level security on every table (see the initial migration).
      2. Composite `(tenant_id, <fk>)` foreign keys, so a row can never point at
         another tenant's row even if application code tries.
      3. ORM guards in `zuschlag_api.db.guards` that scope every SELECT and
         reject flushes that would write a foreign tenant_id.
    """

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805 — declared_attr receives the class
        return mapped_column(
            Uuid,
            ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )


class UuidPk:
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=uuid.uuid4
    )


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
