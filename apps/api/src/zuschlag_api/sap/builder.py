"""Build an ORDERS05 quotation IDoc from a persisted `Quote`."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from zuschlag_api.models import LineItemType, Quote
from zuschlag_api.sap.orders05 import (
    E1EDK01Segment,
    E1EDK02Segment,
    E1EDK14Segment,
    E1EDKA1Segment,
    E1EDP01Segment,
    E1EDP05Segment,
    E1EDP19Segment,
    EDI_DC40Segment,
    Orders05Quotation,
    sap_date,
    sap_decimal,
    sap_time,
)


@dataclass(frozen=True, slots=True)
class SapPartnerProfile:
    """Per-tenant ALE / partner-profile settings (WE20) for the quotation IDoc."""

    client: str  # MANDT
    sales_org: str  # VKORG
    distribution_channel: str  # VTWEG
    division: str  # SPART
    sender_port: str
    sender_partner: str
    receiver_port: str
    receiver_partner: str
    order_type: str = "AG"  # SD quotation
    price_condition: str = "PR00"
    surcharge_condition: str = "ZZUS"  # customer-specific Zuschlag condition type
    labor_material: str = "SRV-LABOR"  # service material for labor lines


class IdocBuildError(ValueError):
    pass


def build_quotation_idoc(
    quote: Quote,
    *,
    profile: SapPartnerProfile,
    sold_to: str,
    created_at: datetime,
    matnr_by_material_id: Mapping[uuid.UUID, str],
    customer_ref: str | None = None,
) -> Orders05Quotation:
    if not quote.line_items:
        raise IdocBuildError(f"quote {quote.quote_number} has no line items")

    items: list[E1EDP01Segment] = []
    for line in quote.line_items:
        if line.item_type is LineItemType.LABOR and line.material_id is None:
            matnr = profile.labor_material
        elif line.material_id is not None and line.material_id in matnr_by_material_id:
            matnr = matnr_by_material_id[line.material_id]
        else:
            raise IdocBuildError(f"line {line.position} has no SAP material number")

        conditions = [
            E1EDP05Segment(KSCHL=profile.price_condition, BETRG=sap_decimal(line.unit_price, 4))
        ]
        if quote.margin_pct:
            conditions.append(
                E1EDP05Segment(
                    ALCKZ="+",
                    KSCHL=profile.surcharge_condition,
                    KPERC=sap_decimal(quote.margin_pct, 3),
                )
            )
        items.append(
            E1EDP01Segment(
                POSEX=str(line.position),
                MENGE=sap_decimal(line.quantity, 3, trim=True),
                MENEE=line.uom,
                E1EDP19=[E1EDP19Segment(QUALF="002", IDTNR=matnr, KTEXT=line.description[:70])],
                E1EDP05=conditions,
            )
        )

    return Orders05Quotation(
        EDI_DC40=EDI_DC40Segment(
            MANDT=profile.client,
            SNDPOR=profile.sender_port,
            SNDPRN=profile.sender_partner,
            RCVPOR=profile.receiver_port,
            RCVPRN=profile.receiver_partner,
            CREDAT=sap_date(created_at),
            CRETIM=sap_time(created_at),
        ),
        E1EDK01=E1EDK01Segment(CURCY=quote.currency, BELNR=quote.quote_number),
        E1EDK14=[
            E1EDK14Segment(QUALF="008", ORGID=profile.sales_org),
            E1EDK14Segment(QUALF="007", ORGID=profile.distribution_channel),
            E1EDK14Segment(QUALF="006", ORGID=profile.division),
            E1EDK14Segment(QUALF="012", ORGID=profile.order_type),
        ],
        E1EDKA1=[E1EDKA1Segment(PARVW="AG", PARTN=sold_to)],
        E1EDK02=[E1EDK02Segment(QUALF="001", BELNR=customer_ref)] if customer_ref else None,
        E1EDP01=items,
    )
