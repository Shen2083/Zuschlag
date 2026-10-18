/**
 * Types shared between apps/api (FastAPI/Pydantic, the source of truth) and apps/web.
 * `paths` drives the typed fetch client; the aliases below name the schemas the UI uses.
 * Monetary and quantity fields are decimal *strings* (Pydantic Decimal), never floats.
 */
import type { components } from "../generated/schema";

export type { components, operations, paths } from "../generated/schema";

type Schemas = components["schemas"];

export type AiSettings = Schemas["AiSettings"];
export type ApproveRequest = Schemas["ApproveRequest"];
export type AuditLogOut = Schemas["AuditLogOut"];
export type CalculateRequest = Schemas["CalculateRequest"];
export type CalculatedLine = Schemas["CalculatedLine"];
export type CalculationOut = Schemas["CalculationOut"];
export type CatalogWarning = Schemas["CatalogWarning"];
export type CustomerList = Schemas["CustomerList"];
export type CustomerOut = Schemas["CustomerOut"];
export type IdocPreview = Schemas["IdocPreview"];
export type ItemUpdate = Schemas["ItemUpdate"];
export type LinkedQuote = Schemas["LinkedQuote"];
export type MatchStatus = Schemas["MatchStatus"];
export type MaterialList = Schemas["MaterialList"];
export type MaterialOut = Schemas["MaterialOut"];
export type PaymentTermsOut = Schemas["PaymentTermsOut"];
export type QuoteCustomer = Schemas["QuoteCustomer"];
export type QuoteDetail = Schemas["QuoteDetail"];
export type QuoteItemKind = Schemas["QuoteItemKind"];
export type QuoteItemOut = Schemas["QuoteItemOut"];
export type QuoteList = Schemas["QuoteList"];
export type QuoteOut = Schemas["QuoteOut"];
export type QuoteStatus = Schemas["QuoteStatus"];
export type QuoteSummary = Schemas["QuoteSummary"];
export type QuotingDefaults = Schemas["QuotingDefaults"];
export type RfqInboxItem = Schemas["RfqInboxItem"];
export type RfqOut = Schemas["RfqOut"];
export type RfqSource = Schemas["RfqSource"];
export type RfqSourceOut = Schemas["RfqSourceOut"];
export type RfqStatus = Schemas["RfqStatus"];
export type SalesAreaOut = Schemas["SalesAreaOut"];
export type SapOutboundProfile = Schemas["SapOutboundProfile"];
export type SapStatus = Schemas["SapStatus"];
export type SendRequest = Schemas["SendRequest"];
export type SendResult = Schemas["SendResult"];
export type Sourcing = Schemas["Sourcing"];
export type TenantSettings = Schemas["TenantSettings"];
export type TrailEvent = Schemas["TrailEvent"];

/** FastAPI error body: `detail` is a message, a validation list, or `{message, reasons}`. */
export interface ApiErrorBody {
  detail?: string | { message: string; reasons: string[] } | Schemas["ValidationError"][];
}
