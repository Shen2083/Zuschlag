"""Read-only views of the mirrored SAP master data (MATMAS, DEBMAS)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.orm import defer, selectinload

from zuschlag_api.api.deps import TenantDb
from zuschlag_api.models import Customer, Material

router = APIRouter(prefix="/api/v1", tags=["master data"])


class MaterialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    matnr: str
    material_type: str | None
    material_group: str | None
    base_uom: str
    description: str | None
    descriptions: dict[str, Any]
    standard_price: Decimal | None
    price_unit: int
    price_currency: str | None
    is_active: bool
    has_embedding: bool
    source_docnum: int | None
    updated_at: datetime


class MaterialList(BaseModel):
    items: list[MaterialOut]
    total: int


@router.get("/materials")
async def list_materials(
    db: TenantDb,
    q: Annotated[str | None, Query(max_length=100)] = None,
    material_type: Annotated[str | None, Query(alias="type", max_length=4)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MaterialList:
    """Material master (MATMAS). `q` matches MATNR and DE/EN short texts."""
    stmt = select(Material)
    if q:
        stmt = stmt.where(Material.search_text.contains(q.strip().lower(), autoescape=True))
    if material_type:
        stmt = stmt.where(Material.material_type == material_type.upper())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await db.execute(
        stmt.add_columns(Material.embedding.is_not(None))
        .options(defer(Material.embedding))  # 1024 floats per row; only presence is shown
        .order_by(Material.matnr)
        .limit(limit)
        .offset(offset)
    )
    fields = MaterialOut.model_fields.keys() - {"has_embedding"}
    return MaterialList(
        total=total or 0,
        items=[
            MaterialOut(**{f: getattr(m, f) for f in fields}, has_embedding=bool(embedded))
            for m, embedded in rows
        ],
    )


class SalesAreaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sales_org: str
    distribution_channel: str
    division: str
    currency: str | None
    payment_terms: str | None
    is_active: bool


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kunnr: str
    name1: str
    name2: str | None
    street: str | None
    postal_code: str | None
    city: str | None
    country: str | None
    language: str | None
    is_active: bool
    sales_areas: list[SalesAreaOut]
    updated_at: datetime


class CustomerList(BaseModel):
    items: list[CustomerOut]
    total: int


@router.get("/customers")
async def list_customers(
    db: TenantDb,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CustomerList:
    """Customer master (DEBMAS) with sales areas (KNVV: currency, ZTERM)."""
    stmt = select(Customer)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(Customer.kunnr.ilike(like), Customer.name1.ilike(like), Customer.city.ilike(like))
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await db.scalars(
        stmt.options(selectinload(Customer.sales_areas))
        .order_by(Customer.kunnr)
        .limit(limit)
        .offset(offset)
    )
    return CustomerList(total=total or 0, items=[CustomerOut.model_validate(c) for c in rows])
