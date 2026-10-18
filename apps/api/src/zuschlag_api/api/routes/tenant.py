"""Tenant settings: SAP partner profile and the quoting defaults in force."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from zuschlag_api.api.deps import PrincipalDep, TenantDb
from zuschlag_api.audit.service import record_audit
from zuschlag_api.core.config import Settings, get_settings
from zuschlag_api.db.session import TENANT_KEY
from zuschlag_api.models import Tenant
from zuschlag_api.sap.reqote import SapOutboundProfile

router = APIRouter(prefix="/api/v1/tenant", tags=["settings"])


class QuotingDefaults(BaseModel):
    zuschlag_pct: Decimal
    vat_rate: Decimal
    payment_terms: str
    currency: str
    review_threshold: float
    labor_rates_eur: dict[str, Decimal]
    labor_default_rate_eur: Decimal


class AiSettings(BaseModel):
    llm_provider: str
    llm_model: str
    llm_region: str
    zero_data_retention_attested: bool
    embedding_provider: str
    embedding_model: str


class TenantSettings(BaseModel):
    name: str
    data_region: str
    sap_client: str | None
    sap_sales_org: str | None
    sap_outbound_profile: SapOutboundProfile | None
    sap_outbound_transport: str
    quoting: QuotingDefaults
    ai: AiSettings


async def _tenant(db: TenantDb) -> Tenant:
    tenant = await db.scalar(select(Tenant).where(Tenant.tenant_id == db.info[TENANT_KEY]))
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant not provisioned")
    return tenant


def _settings_out(tenant: Tenant, s: Settings) -> TenantSettings:
    return TenantSettings(
        name=tenant.name,
        data_region=tenant.data_region,
        sap_client=tenant.sap_client,
        sap_sales_org=tenant.sap_sales_org,
        sap_outbound_profile=SapOutboundProfile.model_validate(tenant.sap_outbound_profile)
        if tenant.sap_outbound_profile
        else None,
        sap_outbound_transport=s.sap_outbound_transport,
        quoting=QuotingDefaults(
            zuschlag_pct=s.quote_default_margin_pct,
            vat_rate=s.quote_default_vat_rate,
            payment_terms=s.quote_default_payment_terms,
            currency=s.quote_default_currency,
            review_threshold=s.rfq_review_threshold,
            labor_rates_eur=s.labor_rates_eur,
            labor_default_rate_eur=s.labor_default_rate_eur,
        ),
        ai=AiSettings(
            llm_provider=s.llm_provider,
            llm_model=s.llm_model,
            llm_region=s.llm_aws_region,
            zero_data_retention_attested=s.llm_zdr_attested,
            embedding_provider=s.embedding_provider,
            embedding_model=s.embedding_model,
        ),
    )


@router.get("")
async def get_tenant_settings(
    db: TenantDb, settings: Annotated[Settings, Depends(get_settings)]
) -> TenantSettings:
    return _settings_out(await _tenant(db), settings)


@router.put("/sap-outbound-profile")
async def put_sap_outbound_profile(
    body: SapOutboundProfile,
    principal: PrincipalDep,
    db: TenantDb,
    settings: Annotated[Settings, Depends(get_settings)],
) -> TenantSettings:
    """ALE partner profile used for outbound REQOTE IDocs (EDI_DC40, partner LF)."""
    tenant = await _tenant(db)
    before = tenant.sap_outbound_profile
    tenant.sap_outbound_profile = body.model_dump(mode="json")
    await record_audit(
        db,
        actor_id=principal.actor_id,
        action="tenant.sap_outbound_profile.updated",
        entity_type="tenant",
        entity_id=tenant.tenant_id,
        ip_sha256=principal.ip_sha256,
        context={"before": before, "after": tenant.sap_outbound_profile},
    )
    await db.flush()
    return _settings_out(tenant, settings)
