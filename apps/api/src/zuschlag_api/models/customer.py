from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKeyConstraint, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from zuschlag_api.db.base import Base, TenantScoped, Timestamps, UuidPk
from zuschlag_api.models.catalog import SapSourced


class Customer(UuidPk, TenantScoped, SapSourced, Timestamps, Base):
    """SAP customer master (KNA1), mirrored from DEBMAS IDocs."""

    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "kunnr"),
    )

    kunnr: Mapped[str] = mapped_column(String(10), nullable=False)
    name1: Mapped[str] = mapped_column(String(40), nullable=False)
    name2: Mapped[str | None] = mapped_column(String(40))
    street: Mapped[str | None] = mapped_column(String(60))  # STRAS
    city: Mapped[str | None] = mapped_column(String(40))  # ORT01
    postal_code: Mapped[str | None] = mapped_column(String(10))  # PSTLZ
    country: Mapped[str | None] = mapped_column(String(3))  # LAND1
    region: Mapped[str | None] = mapped_column(String(3))  # REGIO
    language: Mapped[str | None] = mapped_column(String(2))  # SPRAS as ISO 639-1
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    sales_areas: Mapped[list[CustomerSalesArea]] = relationship(
        back_populates="customer",
        order_by="CustomerSalesArea.sales_org",
        primaryjoin="and_(Customer.tenant_id == foreign(CustomerSalesArea.tenant_id), "
        "Customer.id == foreign(CustomerSalesArea.customer_id))",
        viewonly=True,
    )


class CustomerSalesArea(UuidPk, TenantScoped, Timestamps, Base):
    """SAP customer sales data (KNVV) for one sales org / channel / division."""

    __tablename__ = "customer_sales_areas"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint(
            "customer_id",
            "sales_org",
            "distribution_channel",
            "division",
            name="uq_customer_sales_areas_sales_area",  # default name exceeds 63 chars
        ),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            ondelete="CASCADE",
        ),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    sales_org: Mapped[str] = mapped_column(String(4), nullable=False)  # VKORG
    distribution_channel: Mapped[str] = mapped_column(String(2), nullable=False)  # VTWEG
    division: Mapped[str] = mapped_column(String(2), nullable=False)  # SPART
    currency: Mapped[str | None] = mapped_column(String(3))  # WAERS
    payment_terms: Mapped[str | None] = mapped_column(String(4))  # ZTERM
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    customer: Mapped[Customer] = relationship(
        back_populates="sales_areas",
        primaryjoin="and_(Customer.tenant_id == foreign(CustomerSalesArea.tenant_id), "
        "Customer.id == foreign(CustomerSalesArea.customer_id))",
        viewonly=True,
    )
