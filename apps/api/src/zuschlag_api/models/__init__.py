"""Importing this package registers every table on `Base.metadata`."""

from zuschlag_api.models.audit import AuditLog
from zuschlag_api.models.catalog import Material
from zuschlag_api.models.customer import Customer, CustomerSalesArea
from zuschlag_api.models.idoc_receipt import SapIdocReceipt
from zuschlag_api.models.quote import (
    MatchStatus,
    Quote,
    QuoteAuditTrail,
    QuoteItem,
    QuoteItemKind,
    QuoteStatus,
    Sourcing,
)
from zuschlag_api.models.rfq import Rfq, RfqSource, RfqStatus
from zuschlag_api.models.tenant import Tenant

__all__ = [
    "AuditLog",
    "Customer",
    "CustomerSalesArea",
    "MatchStatus",
    "Material",
    "Quote",
    "QuoteAuditTrail",
    "QuoteItem",
    "QuoteItemKind",
    "QuoteStatus",
    "Rfq",
    "RfqSource",
    "RfqStatus",
    "SapIdocReceipt",
    "Sourcing",
    "Tenant",
]
