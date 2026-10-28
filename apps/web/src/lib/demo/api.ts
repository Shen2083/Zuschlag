/**
 * The Zuschlag.ai API, simulated in the browser for the static demo.
 *
 * The UI talks to it through the normal typed client (lib/api/client.ts), so
 * every screen is the real application. Business rules mirror apps/api:
 * inline edits with cost roll-up, repricing (lib/pricing.ts, the same
 * arithmetic the server is tested against), payment-terms checks, approval
 * and export blockers, GoBD revisions with snapshot hashes, the ORDERS05
 * renderer (byte-compatible with the contract) and SAP's ALEAUD answer.
 *
 * Simulated, and labelled as such in the UI: the AI extraction of new RFQs
 * (a simple local parser instead of a model call), the SAP system, and the
 * audit hash chain for entries made here. State lives in localStorage only.
 * The starting data (seed.json) was captured from the real API.
 */
import type {
  AuditLogOut,
  CalculationOut,
  CustomerOut,
  IdocPreview,
  MaterialOut,
  QuoteDetail,
  QuoteItemOut,
  QuoteSummary,
  RfqInboxItem,
  SapStatus,
  SendResult,
  TenantSettings,
  TrailEvent,
} from "@zuschlag/api-types";

import { Dec } from "@/lib/decimal";
import { QUOTE_ID_POOL } from "@/lib/demo/ids";
import { renderReqote, sha256Hex, type OutboundProfile } from "@/lib/demo/reqote";
import seed from "@/lib/demo/seed.json";
import { calculate, lineInputs, priceLine, type VatPercent } from "@/lib/pricing";
import { clampPct, totalsFor, vatOf, withTotals } from "@/lib/quote-math";

const STORAGE_KEY = "zuschlag-demo-v1";
const ACTOR = "demo.estimator";
export const DEMO_MODEL = "demo-simulation (kein KI-Aufruf)";

type Profile = NonNullable<TenantSettings["sap_outbound_profile"]>;
type RfqRow = NonNullable<QuoteDetail["rfq"]> & { status: RfqInboxItem["status"] };
type Item = QuoteItemOut;

interface ChainEntry {
  seq: number;
  prev: string;
  payload: string;
}

interface State {
  version: 1;
  tenant: TenantSettings;
  materials: MaterialOut[];
  customers: CustomerOut[];
  rfqs: RfqRow[];
  quotes: QuoteDetail[];
  audit: AuditLogOut[];
  chain: ChainEntry[]; // audit entries made in this browser, for verification
  next: { trail: number; docnum: number; sapDocument: number; pool: number };
  sapInbox: Array<{ docnum: string; statuses: string[] }>;
}

class HttpError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : "error");
  }
}

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
const now = () => new Date().toISOString();

// ------------------------------------------------------------------ state

function initialState(): State {
  const s = clone(seed) as unknown as {
    tenant: TenantSettings;
    materials: MaterialOut[];
    customers: CustomerOut[];
    quotes: QuoteDetail[];
    rfqs: RfqInboxItem[];
    audit_logs: AuditLogOut[];
  };
  const rfqs: RfqRow[] = s.quotes
    .filter((q) => q.rfq)
    .map((q) => ({
      ...q.rfq!,
      status: s.rfqs.find((r) => r.id === q.rfq!.id)?.status ?? "quoted",
    }));
  const trailMax = Math.max(0, ...s.quotes.flatMap((q) => q.trail.map((t) => t.id)));
  return {
    version: 1,
    tenant: s.tenant,
    materials: s.materials,
    customers: s.customers,
    rfqs,
    quotes: s.quotes,
    audit: s.audit_logs,
    chain: [],
    next: { trail: trailMax + 1, docnum: 1, sapDocument: 20000001, pool: 0 },
    sapInbox: [],
  };
}

let memory: State | null = null;

function load(): State {
  if (memory) return memory;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as State) : null;
    memory = parsed?.version === 1 ? parsed : initialState();
  } catch {
    memory = initialState();
  }
  return memory;
}

function save(state: State): void {
  memory = state;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // private mode or quota: the demo still works for this page view
  }
}

export function resetDemo(): void {
  memory = null;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // nothing stored
  }
}

// ---------------------------------------------------------------- helpers

function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) =>
      a < b ? -1 : 1,
    );
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${stableStringify(v)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

const posex = (n: number) => String(n).padStart(5, "0");
const revision = (n: number) => `v${n}`;
const fixed = (value: Dec | null, places: number) =>
  value === null ? null : value.toFixed(places);

/** a / b rounded half up to `places` decimals. */
function divide(a: Dec, b: Dec, places: number): Dec {
  const scale = Math.max(a.scale, b.scale);
  const num = a.units * 10n ** BigInt(scale - a.scale) * 10n ** BigInt(places + 1);
  const den = b.units * 10n ** BigInt(scale - b.scale);
  const q = num / den;
  return Dec.from(`${(q + 5n) / 10n}`).shift(places);
}

function* walk(items: Item[]): Generator<{ item: Item; parent: Item | null }> {
  for (const top of items) {
    yield { item: top, parent: null };
    for (const kid of top.components) yield { item: kid, parent: top };
  }
}

function label(item: Item, parent: Item | null): string {
  return parent ? `${parent.position}.${item.position}` : posex(item.position);
}

function quoteOf(state: State, id: string): QuoteDetail {
  const quote = state.quotes.find((q) => q.id === id);
  if (!quote) throw new HttpError(404, `quote ${id} not found`);
  return quote;
}

function customerOf(state: State, quote: QuoteDetail): CustomerOut | undefined {
  return state.customers.find((c) => c.id === quote.customer_id);
}

function trail(state: State, quote: QuoteDetail, event: string, details: TrailEvent["details"]) {
  quote.trail.push({
    id: state.next.trail++,
    timestamp_utc: now(),
    actor_id: ACTOR,
    event,
    details,
  });
}

async function audit(
  state: State,
  action: string,
  entityType: string,
  entityId: string,
  context: Record<string, unknown> | null,
) {
  const seq = Math.max(0, ...state.audit.map((a) => a.seq)) + 1;
  const prev = state.audit.find((a) => a.seq === seq - 1)?.entry_hash ?? "";
  const row = {
    seq,
    timestamp_utc: now(),
    actor_id: ACTOR,
    action,
    entity_type: entityType,
    entity_id: entityId,
    ip_sha256: null,
    context,
  };
  const payload = stableStringify(row);
  state.audit.push({ ...row, entry_hash: await sha256Hex(prev + payload) });
  state.chain.push({ seq, prev, payload });
}

function agreedTerms(state: State, quote: QuoteDetail): string[] {
  const areas = customerOf(state, quote)?.sales_areas ?? [];
  return [
    ...new Set(areas.filter((a) => a.is_active && a.payment_terms).map((a) => a.payment_terms!)),
  ];
}

// ------------------------------------------------------- derived fields

function catalogWarnings(state: State, quote: QuoteDetail): void {
  for (const { item } of walk(quote.items)) {
    let warning: Item["catalog_warning"] = null;
    if (item.kind !== "labor" && item.sourcing !== "internal") {
      const material = item.material_id
        ? state.materials.find((m) => m.id === item.material_id)
        : undefined;
      if (item.material_id) {
        if (!material) warning = "deleted";
        else if (!material.is_active) warning = "inactive";
        else if (material.standard_price === null && item.sourcing !== "custom_build")
          warning = "no_price";
      } else if (item.sourcing === "custom_build") warning = "needs_fert";
      else if (item.sourcing === "missing_in_catalog" || !item.matnr)
        warning = "missing_in_catalog";
    }
    item.catalog_warning = warning;
  }
}

function approveBlockers(quote: QuoteDetail): string[] {
  const reasons: string[] = [];
  if (quote.status === "synced") reasons.push("quote is already synced to SAP");
  if (!quote.calculated_at || !quote.payment_terms) {
    reasons.push("quote has not been calculated (Zuschlag, VAT and payment terms)");
  }
  if (!quote.items.length) reasons.push("quote has no items");
  for (const { item, parent } of walk(quote.items)) {
    if (item.match_status === "NEEDS_HUMAN_REVIEW") {
      reasons.push(`Item ${label(item, parent)}: SAP match needs human review`);
    }
  }
  for (const item of quote.items) {
    if (item.unit_price === null) reasons.push(`Item ${posex(item.position)}: not priced`);
  }
  return reasons;
}

function exportBlockers(state: State, quote: QuoteDetail, requireApproval = true): string[] {
  if (quote.status === "synced") return ["quote is already synced to SAP"];
  const reasons: string[] = [];
  if (requireApproval && quote.status !== "approved") {
    reasons.push(`quote is ${quote.status}; it must be approved before ERP sync`);
  }
  if (!state.tenant.sap_outbound_profile) {
    reasons.push("tenant has no SAP outbound partner profile (sap_outbound_profile)");
  }
  if (!quote.payment_terms) {
    reasons.push("quote has not been calculated (no payment terms); call /calculate first");
  }
  if (!customerOf(state, quote)) reasons.push("quote is not linked to an SAP customer (KUNNR)");
  if (!quote.items.length) reasons.push("quote has no items");
  for (const item of quote.items) {
    const l = `Item ${posex(item.position)}`;
    if (!item.matnr) {
      reasons.push(`${l}: no SAP material number (custom build or missing in catalog)`);
    } else if (item.match_status === "NEEDS_HUMAN_REVIEW") {
      reasons.push(`${l}: SAP match ${item.matnr} is NEEDS_HUMAN_REVIEW`);
    } else if (item.unit_price === null) reasons.push(`${l}: not priced`);
  }
  return reasons;
}

function refresh(state: State, quote: QuoteDetail): QuoteDetail {
  catalogWarnings(state, quote);
  quote.needs_review = quote.status === "needs_review";
  quote.approve_blockers = approveBlockers(quote);
  quote.export_blockers = exportBlockers(state, quote);
  quote.sap_transport = "http";
  quote.customer = (() => {
    const c = customerOf(state, quote);
    return c
      ? {
          id: c.id,
          kunnr: c.kunnr,
          name1: c.name1,
          name2: c.name2,
          street: c.street,
          postal_code: c.postal_code,
          city: c.city,
          country: c.country,
          agreed_payment_terms: agreedTerms(state, quote),
        }
      : null;
  })();
  return quote;
}

// ------------------------------------------------- pricing and revisions

function reprice(quote: QuoteDetail): QuoteDetail {
  const priced = withTotals(
    quote,
    totalsFor(quote, clampPct(Dec.from(quote.margin_pct)), vatOf(quote)),
  );
  const marginFormatted = Dec.from(priced.margin_pct).toFixed(2);
  Object.assign(quote, priced, {
    margin_pct: marginFormatted,
    vat_rate: quote.vat_rate,
    labor_hours: Dec.sum(
      [...walk(priced.items)]
        .filter(({ item }) => item.kind === "labor")
        .map(({ item }) => Dec.tryFrom(item.labor_hours) ?? Dec.ZERO),
    ).toFixed(2),
  });
  for (const item of quote.items) if (item.margin_pct) item.margin_pct = marginFormatted;
  return quote;
}

function snapshot(quote: QuoteDetail) {
  return {
    quote_number: quote.quote_number,
    revision: revision(quote.revision),
    currency: quote.currency,
    customer_id: quote.customer_id,
    margin_pct: quote.margin_pct,
    material_cost: quote.material_cost,
    labor_cost: quote.labor_cost,
    total_cost: quote.total_cost,
    net_total: quote.net_total,
    vat_rate: quote.vat_rate,
    vat_amount: quote.vat_amount,
    gross_total: quote.gross_total,
    payment_terms: quote.payment_terms,
    items: [...walk(quote.items)].map(({ item }) => ({
      id: item.id,
      parent_item_id: item.parent_item_id,
      position: item.position,
      kind: item.kind,
      matnr: item.matnr,
      description: item.description,
      quantity: item.quantity,
      uom: item.uom,
      unit_cost: item.unit_cost,
      unit_price: item.unit_price,
      line_total: item.line_total,
    })),
  };
}

async function openRevision(state: State, quote: QuoteDetail, reason: string): Promise<void> {
  const frozen = snapshot(quote);
  quote.revision += 1;
  quote.status = "draft";
  trail(state, quote, "quote.revision.created", {
    revision: revision(quote.revision),
    supersedes: frozen.revision,
    reason,
    frozen_snapshot: frozen,
    frozen_snapshot_sha256: await sha256Hex(stableStringify(frozen)),
  });
}

function rollup(quote: QuoteDetail): void {
  for (const top of quote.items) {
    for (const kid of top.components) {
      if (kid.kind === "labor") kid.labor_hours = Dec.from(kid.quantity).quantize(2).toFixed(2);
      const cost = Dec.tryFrom(kid.unit_cost);
      kid.extended_cost = cost ? cost.mul(kid.quantity).quantize(2).toFixed(2) : null;
    }
    if (top.components.length) {
      const priced = top.components.every(
        (k) => k.unit_cost !== null && k.quantity_per_parent !== null,
      );
      top.unit_cost = priced
        ? Dec.sum(top.components.map((k) => Dec.from(k.unit_cost!).mul(k.quantity_per_parent!)))
            .quantize(4)
            .toFixed(4)
        : null;
    }
    const cost = Dec.tryFrom(top.unit_cost);
    top.extended_cost = cost ? cost.mul(top.quantity).quantize(2).toFixed(2) : null;
  }
}

// ------------------------------------------------------------ handlers

interface ItemPatch {
  quantity?: string | number | null;
  matnr?: string | null;
  description?: string | null;
  uom?: string | null;
  unit_cost?: string | number | null;
}

function findMaterial(state: State, matnr: string): MaterialOut | undefined {
  const key = matnr.trim();
  return (
    state.materials.find((m) => m.matnr === key) ??
    (/^\d+$/.test(key) ? state.materials.find((m) => m.matnr === key.padStart(18, "0")) : undefined)
  );
}

async function editItem(state: State, quoteId: string, itemId: string, patch: ItemPatch) {
  const quote = quoteOf(state, quoteId);
  if (quote.status === "synced") {
    throw new HttpError(409, `quote ${quote.quote_number} is already synced to SAP`);
  }
  const found = [...walk(quote.items)].find(({ item }) => item.id === itemId);
  if (!found) throw new HttpError(404, `item ${itemId} not found`);
  const { item, parent } = found;
  const fields = Object.keys(patch) as (keyof ItemPatch)[];
  if (!fields.length) throw new HttpError(422, "nothing to change");
  const kids = item.components;
  const before = {
    quantity: item.quantity,
    matnr: item.matnr,
    description: item.description,
    uom: item.uom,
    unit_cost: item.unit_cost,
    match_status: item.match_status,
  };
  const reopened = quote.status === "approved";
  if (reopened) await openRevision(state, quote, "item.edited");

  if ("matnr" in patch) {
    if (item.kind === "labor") throw new HttpError(422, "labor operations have no SAP material");
    const matnr = patch.matnr?.trim();
    if (!matnr) {
      Object.assign(item, {
        material_id: null,
        matnr: null,
        material_type: null,
        match_status: kids.length ? "NOT_APPLICABLE" : "NEEDS_HUMAN_REVIEW",
        match_method: "manual",
        match_confidence: null,
      });
      if (!kids.length) Object.assign(item, { sourcing: "missing_in_catalog", unit_cost: null });
    } else {
      const material = findMaterial(state, matnr);
      if (!material)
        throw new HttpError(422, `material ${matnr} not found in the SAP material master (MATMAS)`);
      if (!material.is_active)
        throw new HttpError(422, `material ${material.matnr} is inactive in SAP`);
      Object.assign(item, {
        material_id: material.id,
        matnr: material.matnr,
        material_type: material.material_type,
        match_status: "MATCHED",
        match_method: "manual",
        match_confidence: "1.00",
      });
      if (material.description) item.description = material.description.slice(0, 300);
      if (!kids.length) {
        item.sourcing = "catalog";
        // SAP prices are per PEINH (price_unit) base units.
        item.unit_cost =
          material.standard_price === null
            ? null
            : divide(
                Dec.from(material.standard_price),
                Dec.from(Math.max(material.price_unit, 1)),
                4,
              ).toFixed(4);
      }
    }
  }
  if ("description" in patch) {
    const text = (patch.description ?? "").trim();
    if (!text) throw new HttpError(422, "description must not be empty");
    item.description = text.slice(0, 300);
  }
  if ("uom" in patch) {
    const uom = (patch.uom ?? "").trim().toUpperCase();
    if (!/^[A-Z0-9]{2,3}$/.test(uom)) {
      throw new HttpError(422, "unit must be an ISO unit code such as PCE, KGM or HUR");
    }
    item.uom = uom;
  }
  if ("unit_cost" in patch) {
    if (kids.length)
      throw new HttpError(422, "the cost of a custom build is rolled up from its components");
    const cost =
      patch.unit_cost === null || patch.unit_cost === undefined
        ? null
        : Dec.from(String(patch.unit_cost));
    if (cost?.isNegative()) throw new HttpError(422, "unit cost must not be negative");
    item.unit_cost = fixed(cost?.quantize(4) ?? null, 4);
    if (item.kind === "labor" && cost) item.labor_rate = cost.quantize(2).toFixed(2);
  }
  if ("quantity" in patch) {
    const qty = Dec.tryFrom(patch.quantity === null ? null : String(patch.quantity));
    if (!qty || qty.cmp(0) <= 0) throw new HttpError(422, "quantity must be greater than zero");
    const q3 = qty.quantize(3);
    item.quantity = q3.toFixed(3);
    if (parent) item.quantity_per_parent = divide(q3, Dec.from(parent.quantity), 3).toFixed(3);
    for (const kid of kids) {
      if (kid.quantity_per_parent !== null) {
        kid.quantity = Dec.from(kid.quantity_per_parent).mul(q3).quantize(3).toFixed(3);
      }
    }
  }

  rollup(quote);
  reprice(quote);
  quote.updated_at = now();
  const after = {
    quantity: item.quantity,
    matnr: item.matnr,
    description: item.description,
    uom: item.uom,
    unit_cost: item.unit_cost,
    match_status: item.match_status,
  };
  trail(state, quote, "item.edited", {
    item_id: item.id,
    revision: revision(quote.revision),
    position: label(item, parent),
    changed: Object.keys(after)
      .filter((k) => after[k as keyof typeof after] !== before[k as keyof typeof before])
      .sort(),
    before,
    after,
    net_total: quote.net_total,
    approval_revoked: reopened,
  });
  await audit(state, "quote.item.edited", "quote", quote.id, {
    item_id: item.id,
    fields: fields.sort(),
  });
  return refresh(state, quote);
}

function resolveTerms(
  state: State,
  quote: QuoteDetail,
  requested: string | null | undefined,
  allow: boolean,
) {
  const agreed = agreedTerms(state, quote);
  const chosen = (requested || agreed[0] || state.tenant.quoting.payment_terms)
    .trim()
    .toUpperCase();
  const net = /^NT(\d{1,3})$/.exec(chosen);
  const catalog: Record<string, number> = { "0001": 0 };
  if (!chosen || chosen.length > 4) {
    throw new HttpError(422, `invalid payment terms key '${chosen}' (ZTERM is 1-4 characters)`);
  }
  const days = net ? Number(net[1]) : catalog[chosen];
  if (days === undefined) {
    throw new HttpError(
      422,
      `unknown payment terms '${chosen}': use NT<days> or declare the key in PAYMENT_TERMS_CATALOG`,
    );
  }
  const deviation = agreed.length > 0 && !agreed.includes(chosen);
  if (deviation && !allow) {
    throw new HttpError(
      422,
      `payment terms ${chosen} deviate from the customer's agreed terms ${agreed.join(", ")} (set allow_terms_deviation to override)`,
    );
  }
  return {
    zterm: chosen,
    net_days: days,
    description_de: days === 0 ? "sofort zahlbar ohne Abzug" : `${days} Tage netto`,
    description_en: days === 0 ? "due immediately, no discount" : `net ${days} days`,
    agreed,
    deviation,
  };
}

async function calculateQuote(
  state: State,
  quoteId: string,
  body: {
    zuschlag_pct: string | number;
    vat_rate?: number;
    payment_terms?: string | null;
    allow_terms_deviation?: boolean;
  },
): Promise<CalculationOut> {
  const quote = quoteOf(state, quoteId);
  if (quote.status === "synced") {
    throw new HttpError(409, `quote ${quote.quote_number} is already synced to SAP`);
  }
  const pct = Dec.from(String(body.zuschlag_pct));
  if (pct.isNegative() || pct.cmp(100) > 0) {
    throw new HttpError(422, [
      { loc: ["body", "zuschlag_pct"], msg: "Input should be between 0 and 100", type: "range" },
    ]);
  }
  const vat = (body.vat_rate ?? 19) as VatPercent;
  if (vat !== 19 && vat !== 7) {
    throw new HttpError(422, [
      { loc: ["body", "vat_rate"], msg: "Input should be 19 or 7", type: "literal_error" },
    ]);
  }
  const terms = resolveTerms(state, quote, body.payment_terms, body.allow_terms_deviation ?? false);
  const totals = calculate(lineInputs(quote.items), pct, vat);

  const unchanged =
    Dec.from(quote.margin_pct).eq(pct) &&
    quote.vat_rate !== null &&
    Dec.from(quote.vat_rate).eq(vat) &&
    quote.payment_terms === terms.zterm &&
    Dec.from(quote.net_total).eq(totals.netAmount) &&
    Dec.from(quote.gross_total).eq(totals.grossAmount);
  const skip = quote.status === "approved" && unchanged;
  if (!skip) {
    if (quote.status === "approved") await openRevision(state, quote, "quote.calculated");
    const before = {
      margin_pct: quote.margin_pct,
      net_total: quote.net_total,
      gross_total: quote.gross_total,
      payment_terms: quote.payment_terms,
    };
    quote.margin_pct = pct.toFixed(2);
    quote.vat_rate = Dec.from(vat).toFixed(2);
    reprice(quote);
    quote.payment_terms = terms.zterm;
    quote.calculated_at = now();
    quote.updated_at = now();
    trail(state, quote, "quote.calculated", {
      revision: revision(quote.revision),
      before,
      after: {
        margin_pct: quote.margin_pct,
        factory_cost: totals.factoryCost.toFixed(2),
        net_total: quote.net_total,
        vat_rate: String(vat),
        vat_amount: quote.vat_amount,
        gross_total: quote.gross_total,
        payment_terms: terms.zterm,
      },
      payment_terms_deviation: terms.deviation,
      agreed_payment_terms: terms.agreed,
      missing_price_positions: totals.missingPricePositions,
    });
    refresh(state, quote);
  }
  const inputs = new Map(lineInputs(quote.items).map((l) => [l.itemId, l]));
  return {
    quote_id: quote.id,
    quote_number: quote.quote_number,
    currency: quote.currency,
    material_cost: totals.materialCost.toFixed(2),
    labor_cost: totals.laborCost.toFixed(2),
    factory_cost: totals.factoryCost.toFixed(2),
    zuschlag_pct: pct.toString(),
    zuschlag_amount: totals.zuschlagAmount.toFixed(2),
    net_amount: totals.netAmount.toFixed(2),
    vat_rate: String(vat),
    vat_amount: totals.vatAmount.toFixed(2),
    gross_amount: totals.grossAmount.toFixed(2),
    payment_terms: terms,
    complete: totals.missingPricePositions.length === 0,
    missing_price_positions: totals.missingPricePositions,
    lines: totals.lines.map((l) => {
      const input = inputs.get(l.itemId)!;
      return {
        position: l.position,
        quantity: String(input.quantity),
        unit_cost: l.unitCost.toFixed(4),
        material_cost: Dec.from(input.materialCost).toFixed(2),
        labor_cost: Dec.from(input.laborCost).toFixed(2),
        factory_cost: l.factoryCost.toFixed(2),
        zuschlag_pct: pct.toString(),
        unit_zuschlag: l.unitZuschlag.toFixed(4),
        unit_price: l.unitPrice.toFixed(4),
        net_amount: l.netAmount.toFixed(2),
      };
    }),
  };
}

async function approve(state: State, quoteId: string, comment: string | null) {
  const quote = quoteOf(state, quoteId);
  if (quote.status === "synced") {
    throw new HttpError(409, `quote ${quote.quote_number} is already synced to SAP`);
  }
  if (quote.status === "approved") return refresh(state, quote);
  const reasons = approveBlockers(quote);
  if (reasons.length) {
    throw new HttpError(422, { message: "quote cannot be approved yet", reasons });
  }
  const previous = quote.status;
  quote.status = "approved";
  quote.updated_at = now();
  const frozen = snapshot(quote);
  trail(state, quote, "quote.approved", {
    revision: revision(quote.revision),
    snapshot: frozen,
    snapshot_sha256: await sha256Hex(stableStringify(frozen)),
    previous_status: previous,
    acknowledged_review_reasons: quote.review_reasons,
    net_total: quote.net_total,
    gross_total: quote.gross_total,
    margin_pct: quote.margin_pct,
    payment_terms: quote.payment_terms,
    comment: comment?.slice(0, 500) || null,
    approved_at: now(),
  });
  await audit(state, "quote.approved", "quote", quote.id, {
    net_total: quote.net_total,
    currency: quote.currency,
  });
  return refresh(state, quote);
}

// ----------------------------------------------- new quotes (pool ids)

function takeQuoteId(state: State): string {
  const id = QUOTE_ID_POOL[state.next.pool];
  if (!id) {
    throw new HttpError(
      503,
      "Demo: alle vorbereiteten Angebotsseiten sind belegt. Bitte die Demo oben zurücksetzen.",
    );
  }
  state.next.pool += 1;
  return id;
}

function quoteNumber(): string {
  const day = new Date().toISOString().slice(0, 10).replaceAll("-", "");
  const suffix = Array.from(crypto.getRandomValues(new Uint8Array(3)), (b) =>
    b.toString(16).padStart(2, "0"),
  )
    .join("")
    .toUpperCase();
  return `AN-${day}-${suffix}`;
}

function cloneQuote(state: State, source: QuoteDetail, rfq: RfqRow | null): QuoteDetail {
  const ids = new Map<string, string>();
  const fresh = (old: string) => {
    const id = crypto.randomUUID();
    ids.set(old, id);
    return id;
  };
  const copy = clone(source);
  copy.id = takeQuoteId(state);
  copy.quote_number = quoteNumber();
  copy.created_at = now();
  copy.updated_at = now();
  copy.revision = 1;
  copy.last_idoc_docnum = null;
  copy.exported_at = null;
  copy.rfq = rfq ?? copy.rfq;
  copy.rfq_id = copy.rfq?.id ?? null;
  for (const top of copy.items) {
    top.id = fresh(top.id);
    for (const kid of top.components) {
      kid.id = fresh(kid.id);
      kid.parent_item_id = top.id;
    }
  }
  copy.trail = copy.trail
    .filter((t) =>
      ["rfq.received", "ai.extraction", "ai.matching", "quote.priced", "quote.created"].includes(
        t.event,
      ),
    )
    .map((t) => ({ ...t, id: state.next.trail++, timestamp_utc: now() }));
  return copy;
}

async function reparse(state: State, quoteId: string): Promise<QuoteDetail> {
  const old = quoteOf(state, quoteId);
  const rfq = state.rfqs.find((r) => r.id === old.rfq_id);
  if (!rfq?.body_text) throw new HttpError(409, "quote has no source RFQ text to re-parse");
  const recorded = (seed.quotes as unknown as QuoteDetail[]).find((q) => q.rfq_id === rfq.id);
  // Seed RFQs replay their recorded extraction (as the server's tests do); others are re-parsed locally.
  const fresh = recorded
    ? cloneQuote(state, recorded, rfq)
    : simulatePipeline(state, rfq, old.customer?.kunnr ?? null);
  state.quotes.push(fresh);
  trail(state, old, "quote.superseded", {
    by_quote_id: fresh.id,
    by_quote_number: fresh.quote_number,
  });
  await audit(state, "quote.generated_from_rfq", "quote", fresh.id, {
    rfq_id: rfq.id,
    status: fresh.status,
  });
  refresh(state, old);
  return refresh(state, fresh);
}

// ---------------------------------------- simulated extraction + matching

const UNITS: Record<string, string> = {
  stück: "PCE",
  stk: "PCE",
  st: "PCE",
  pcs: "PCE",
  pieces: "PCE",
  piece: "PCE",
  units: "PCE",
  x: "PCE",
  kg: "KGM",
  m: "MTR",
  meter: "MTR",
  m2: "MTK",
  h: "HUR",
  std: "HUR",
};
const KIND_BY_TYPE: Record<string, Item["kind"]> = {
  FERT: "finished_good",
  HALB: "semi_finished",
  ROH: "raw_material",
  HAWA: "purchased_part",
  DIEN: "service",
};

function words(text: string): Set<string> {
  return new Set(
    text
      .toLowerCase()
      .split(/[^\p{L}\p{N}.]+/u)
      .filter((w) => w.length > 1),
  );
}

function similarity(a: string, b: string): number {
  const x = words(a);
  const y = words(b);
  const common = [...x].filter((w) => y.has(w)).length;
  return x.size && y.size ? common / Math.min(x.size, y.size) : 0;
}

interface SimMatch {
  material: MaterialOut | null;
  confidence: number;
  method: string;
}

function match(state: State, description: string, text: string): SimMatch {
  const norm = (s: string) => s.toLowerCase().replace(/\s+/g, " ").trim();
  const wanted = norm(description);
  for (const m of state.materials.filter((x) => x.is_active)) {
    const texts = [m.description ?? "", ...Object.values(m.descriptions as Record<string, string>)];
    if (texts.some((t) => norm(t) === wanted))
      return { material: m, confidence: 0.97, method: "exact_text" };
  }
  const tokens = new Set(
    (text.match(/[A-Za-z0-9][A-Za-z0-9._/-]{3,39}/g) ?? []).map((t) => t.toUpperCase()),
  );
  const cited = state.materials.find(
    (m) => m.is_active && tokens.has(m.matnr.toUpperCase()) && /\d/.test(m.matnr),
  );
  if (cited) return { material: cited, confidence: 0.95, method: "exact" };
  let best: SimMatch = { material: null, confidence: 0, method: "none" };
  for (const m of state.materials.filter((x) => x.is_active)) {
    const score = Math.max(
      similarity(description, m.description ?? ""),
      ...Object.values(m.descriptions as Record<string, string>).map((t) =>
        similarity(description, t),
      ),
    );
    if (score > best.confidence)
      best = { material: m, confidence: Math.min(0.89, score), method: "lexical" };
  }
  return best;
}

function simulatePipeline(state: State, rfq: RfqRow, customerRef: string | null): QuoteDetail {
  const text = rfq.body_text ?? "";
  const lineRe =
    /(\d+(?:[.,]\d+)?)\s*(stück|stk\.?|st\.|pcs\.?|pieces?|units|x|kg|m2|m|h|std\.?)\s+([^\n;]+)/gi;
  const found = [...text.matchAll(lineRe)];
  if (!found.length) {
    throw new HttpError(
      502,
      'Demo: keine Positionen erkannt. Die Demo simuliert die KI lokal und erwartet z. B. "100 Stück Shen AI Product Description".',
    );
  }
  const margin = Dec.from(state.tenant.quoting.zuschlag_pct);
  const customer = customerRef
    ? state.customers.find(
        (c) =>
          c.id === customerRef ||
          c.kunnr === (/^\d+$/.test(customerRef) ? customerRef.padStart(10, "0") : customerRef),
      )
    : state.customers.find((c) => text.toLowerCase().includes(c.name1.toLowerCase()));
  if (customerRef && !customer) throw new HttpError(404, `customer ${customerRef} not found`);

  const reasons: string[] = [];
  const items: Item[] = found.map((m, index) => {
    const quantity = Dec.from(m[1]!.replace(",", ".")).quantize(3);
    const unit = UNITS[m[2]!.toLowerCase().replace(".", "")] ?? "PCE";
    const description = m[3]!.trim().replace(/[.,!?]+$/, "");
    const position = (index + 1) * 10;
    const hit = match(state, description, description);
    const linked = hit.material && hit.confidence >= 0.6 ? hit.material : null;
    const status: Item["match_status"] =
      linked && hit.confidence >= 0.75 ? "MATCHED" : "NEEDS_HUMAN_REVIEW";
    if (!linked)
      reasons.push(
        `Item ${position} '${description.slice(0, 60)}': not found in SAP catalog (missing material)`,
      );
    else if (status !== "MATCHED") {
      reasons.push(
        `Item ${position} '${description.slice(0, 60)}': match ${linked.matnr} has confidence ${hit.confidence.toFixed(2)} (NEEDS_HUMAN_REVIEW)`,
      );
    }
    const unitCost = linked?.standard_price
      ? divide(Dec.from(linked.standard_price), Dec.from(Math.max(linked.price_unit, 1)), 4)
      : null;
    if (!unitCost) reasons.push(`Item ${position}: no price available`);
    const priced = unitCost ? priceLine(unitCost, quantity, margin) : null;
    return {
      id: crypto.randomUUID(),
      parent_item_id: null,
      position,
      kind: (linked?.material_type && KIND_BY_TYPE[linked.material_type]) || "purchased_part",
      description: description.slice(0, 300),
      requested_description: description.slice(0, 1000),
      specs: [],
      quantity: quantity.toFixed(3),
      quantity_per_parent: null,
      uom: unit,
      material_id: linked?.id ?? null,
      matnr: linked?.matnr ?? null,
      material_type: linked?.material_type ?? null,
      match_status: status,
      match_confidence: hit.confidence.toFixed(2),
      match_method: hit.method,
      match_candidates: [],
      sourcing: linked ? "catalog" : "missing_in_catalog",
      unit_cost: fixed(priced?.unitCost ?? null, 4),
      labor_hours: null,
      labor_rate: null,
      extended_cost: unitCost ? unitCost.mul(quantity).quantize(2).toFixed(2) : null,
      margin_pct: priced ? margin.toFixed(2) : null,
      unit_margin: fixed(priced?.unitZuschlag ?? null, 4),
      unit_price: fixed(priced?.unitPrice ?? null, 4),
      line_total: fixed(priced?.lineTotal ?? null, 2),
      catalog_warning: null,
      components: [],
    };
  });

  const german = /\b(bitte|angebot|stück|anfrage)\b/i.test(text);
  const quote = {
    id: takeQuoteId(state),
    quote_number: quoteNumber(),
    status: reasons.length ? "needs_review" : "draft",
    revision: 1,
    needs_review: reasons.length > 0,
    review_reasons: reasons,
    rfq_id: rfq.id,
    customer_id: customer?.id ?? null,
    customer_name: customer?.name1 ?? null,
    contact_name: null,
    contact_email: null,
    requested_delivery_date: null,
    language: german ? "de" : "en",
    currency: "EUR",
    margin_pct: margin.toFixed(2),
    material_cost: "0.00",
    labor_hours: "0.00",
    labor_cost: "0.00",
    total_cost: "0.00",
    net_total: "0.00",
    llm_model: DEMO_MODEL,
    llm_compliance_hash: null,
    extraction: {
      language: german ? "de" : "en",
      summary: rfq.subject,
      customer: { company_name: customer?.name1 ?? null },
      line_items: items.map((i) => ({
        position: i.position / 10,
        description: i.description,
        quantity: Number(i.quantity),
        unit: i.uom,
        specs: [],
      })),
      open_questions: [],
    },
    items,
    vat_rate: null,
    vat_amount: "0.00",
    gross_total: "0.00",
    payment_terms: null,
    calculated_at: null,
    last_idoc_docnum: null,
    exported_at: null,
    created_at: now(),
    updated_at: now(),
    rfq,
    customer: null,
    trail: [],
    approve_blockers: [],
    export_blockers: [],
    sap_transport: "http",
  } as QuoteDetail;
  reprice(quote);
  quote.vat_amount = "0.00";
  quote.gross_total = "0.00";
  trail(state, quote, "rfq.received", { rfq_id: rfq.id, chars: text.length });
  trail(state, quote, "ai.extraction", {
    model: DEMO_MODEL,
    line_items: items.length,
    simulated: true,
  });
  trail(state, quote, "ai.matching", {
    items: items.map((i) => ({
      position: String(i.position),
      matnr: i.matnr,
      confidence: Number(i.match_confidence),
      status: i.match_status,
      method: i.match_method,
    })),
  });
  trail(state, quote, "quote.created", { status: quote.status, review_reasons: reasons });
  return quote;
}

async function generate(state: State, body: { raw_text: string; customer_id?: string | null }) {
  const text = body.raw_text ?? "";
  if (!text.trim())
    throw new HttpError(422, [
      { loc: ["body", "raw_text"], msg: "Field required", type: "missing" },
    ]);
  const rfq: RfqRow = {
    id: crypto.randomUUID(),
    source: "manual",
    subject: (text.trim().split("\n")[0] ?? "RFQ").slice(0, 120),
    customer_ref: null,
    body_text: text,
    attachment_object_key: null,
    received_at: now(),
    status: "quoted",
  };
  const quote = simulatePipeline(state, rfq, body.customer_id?.trim() || null);
  state.rfqs.push(rfq);
  state.quotes.push(quote);
  await audit(state, "quote.generated_from_rfq", "quote", quote.id, {
    rfq_id: rfq.id,
    status: quote.status,
    simulated: true,
  });
  return refresh(state, quote);
}

// ------------------------------------------------------- SAP (simulated)

function renderFor(state: State, quote: QuoteDetail, docnum: string): string {
  const profile = state.tenant.sap_outbound_profile as OutboundProfile;
  const c = customerOf(state, quote)!;
  const cut = (v: string | null | undefined, n: number) => (v ? v.slice(0, n) : null);
  return renderReqote(
    {
      docnum,
      belnr: quote.quote_number,
      curcy: quote.currency,
      zterm: quote.payment_terms!,
      soldTo: {
        partn: c.kunnr,
        name1: c.name1.slice(0, 35),
        name2: cut(c.name2, 35),
        stras: cut(c.street, 35),
        ort01: cut(c.city, 35),
        pstlz: c.postal_code,
        land1: c.country,
      },
      items: quote.items.map((i) => ({
        posex: i.position,
        menge: i.quantity,
        menee: i.uom,
        idnlf: i.matnr!,
        ktext: i.description.slice(0, 70),
      })),
    },
    profile,
  );
}

async function prepare(state: State, quoteId: string): Promise<IdocPreview> {
  const quote = quoteOf(state, quoteId);
  if (quote.status === "synced")
    throw new HttpError(409, `quote ${quote.quote_number} is already synced to SAP`);
  const reasons = exportBlockers(state, quote);
  if (reasons.length) throw new HttpError(422, { message: "quote not ready for SAP", reasons });
  const docnum = String(state.next.docnum++).padStart(16, "0");
  const xml = renderFor(state, quote, docnum);
  const sha256 = await sha256Hex(xml);
  const receiver = (state.tenant.sap_outbound_profile as Profile).receiver_partner;
  trail(state, quote, "sap.idoc.prepared", {
    idoc_type: "ORDERS05",
    message_type: "REQOTE",
    docnum,
    receiver,
    items: quote.items.length,
    xml_sha256: sha256,
  });
  return { docnum, sha256, xml, receiver, transport: "http" };
}

async function send(
  state: State,
  quoteId: string,
  body: { docnum: string; sha256: string },
): Promise<SendResult> {
  const quote = quoteOf(state, quoteId);
  if (quote.status === "synced")
    throw new HttpError(409, `quote ${quote.quote_number} is already synced to SAP`);
  const reasons = exportBlockers(state, quote);
  if (reasons.length) throw new HttpError(422, { message: "quote not ready for SAP", reasons });
  const prepared = [...quote.trail]
    .reverse()
    .find((t) => t.event === "sap.idoc.prepared" && t.details?.docnum === body.docnum);
  if (!prepared) throw new HttpError(409, `IDoc ${body.docnum} was not prepared for this quote`);
  const xml = renderFor(state, quote, body.docnum);
  const sha256 = await sha256Hex(xml);
  if (sha256 !== prepared.details?.xml_sha256 || sha256 !== body.sha256) {
    throw new HttpError(
      409,
      "the quote changed after the IDoc preview; review the new payload before sending",
    );
  }

  // The receiving SAP system checks the IDoc against its own master data (see tests/mock_sap).
  const errors: string[] = [];
  const sold = customerOf(state, quote);
  if (!sold) errors.push("Auftraggeber unbekannt");
  for (const item of quote.items) {
    if (!state.materials.some((m) => m.matnr === item.matnr)) {
      errors.push(`Position ${posex(item.position)}: Material ${item.matnr} unbekannt`);
    }
  }
  const statuses = [
    {
      docnum: body.docnum,
      status: "06",
      text: "IDoc empfangen, Syntax OK",
      object_key: null as string | null,
    },
  ];
  if (errors.length) {
    statuses.push({ docnum: body.docnum, status: "51", text: errors.join("; "), object_key: null });
    state.sapInbox.push({ docnum: body.docnum, statuses: statuses.map((s) => s.status) });
    throw new HttpError(502, {
      message: `SAP rejected the IDoc (status 51): ${errors.join("; ")}`,
      reasons: errors,
    });
  }
  const document = String(state.next.sapDocument++).padStart(10, "0");
  statuses.push({
    docnum: body.docnum,
    status: "53",
    text: `Angebot ${document} angelegt`,
    object_key: document,
  });
  state.sapInbox.push({ docnum: body.docnum, statuses: statuses.map((s) => s.status) });

  const sentAt = now();
  const reference = `http:200:REQOTE_${body.docnum}.xml`;
  quote.last_idoc_docnum = body.docnum;
  quote.exported_at = sentAt;
  quote.status = "synced";
  quote.updated_at = sentAt;
  trail(state, quote, "sap.idoc.sent", {
    idoc_type: "ORDERS05",
    message_type: "REQOTE",
    docnum: body.docnum,
    receiver: (state.tenant.sap_outbound_profile as Profile).receiver_partner,
    transport: "http",
    target: "demo-sap (simuliert)",
    reference,
    sap_status: statuses,
    xml_sha256: sha256,
  });
  await audit(state, "sap.reqote.sent", "quote", quote.id, {
    docnum: body.docnum,
    xml_sha256: sha256,
    transport: "http",
  });
  return {
    docnum: body.docnum,
    sha256,
    transport: "http",
    reference,
    sent_at: sentAt,
    sap_status: statuses,
    quote: refresh(state, quote),
  };
}

function sapStatus(state: State): SapStatus {
  const profile = state.tenant.sap_outbound_profile;
  const outbound =
    state.quotes
      .map((q) => q.exported_at)
      .filter(Boolean)
      .sort()
      .pop() ?? null;
  return {
    state: profile ? "connected" : "not_configured",
    detail: profile ? "Demo-SAP (simuliert im Browser)" : "no SAP partner profile",
    system_id: profile?.sender_partner ?? null,
    client: profile?.mandt ?? null,
    receiver: profile?.receiver_partner ?? null,
    transport: "http",
    latency_ms: Math.round((3 + Math.random() * 6) * 10) / 10,
    last_inbound_at: state.audit.find((a) => a.action.startsWith("sap."))?.timestamp_utc ?? null,
    last_outbound_at: outbound,
    checked_at: now(),
  };
}

// --------------------------------------------------------------- lists

function summaries(state: State, params: URLSearchParams) {
  const status = params.get("status");
  const q = (params.get("q") ?? "").toLowerCase();
  const rows: QuoteSummary[] = state.quotes
    .filter((quote) => !status || quote.status === status)
    .map((quote) => ({
      id: quote.id,
      quote_number: quote.quote_number,
      status: quote.status,
      customer_name: quote.customer_name,
      kunnr: customerOf(state, quote)?.kunnr ?? null,
      rfq_subject: quote.rfq?.subject ?? null,
      currency: quote.currency,
      margin_pct: quote.margin_pct,
      net_total: quote.net_total,
      gross_total: quote.gross_total,
      items: quote.items.length,
      review_items: [...walk(quote.items)].filter(
        ({ item }) => item.match_status === "NEEDS_HUMAN_REVIEW",
      ).length,
      requested_delivery_date: quote.requested_delivery_date,
      created_at: quote.created_at,
      updated_at: quote.updated_at,
    }))
    .filter(
      (r) =>
        !q ||
        [r.quote_number, r.customer_name, r.kunnr, r.rfq_subject].some((v) =>
          v?.toLowerCase().includes(q),
        ),
    )
    .sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  return page(rows, params, 50);
}

function page<T>(rows: T[], params: URLSearchParams, defaultLimit: number) {
  const offset = Number(params.get("offset") ?? 0);
  const limit = Number(params.get("limit") ?? defaultLimit);
  return { items: rows.slice(offset, offset + limit), total: rows.length };
}

function inbox(state: State): RfqInboxItem[] {
  return [...state.rfqs]
    .sort((a, b) => (a.received_at < b.received_at ? 1 : -1))
    .map((r) => {
      const latest = state.quotes
        .filter((q) => q.rfq_id === r.id)
        .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
      return {
        id: r.id,
        source: r.source,
        status: r.status,
        subject: r.subject,
        customer_ref: r.customer_ref,
        received_at: r.received_at,
        preview: r.body_text?.slice(0, 240) || null,
        quote: latest
          ? {
              id: latest.id,
              quote_number: latest.quote_number,
              status: latest.status,
              net_total: latest.net_total,
              currency: latest.currency,
            }
          : null,
      };
    });
}

async function verifyChain(state: State) {
  const breaks: Array<{ seq: number; reason: string }> = [];
  const bySeq = new Map(state.audit.map((a) => [a.seq, a]));
  for (const entry of state.chain) {
    const stored = bySeq.get(entry.seq);
    const expected = await sha256Hex(entry.prev + entry.payload);
    if (!stored || stored.entry_hash !== expected)
      breaks.push({ seq: entry.seq, reason: "hash mismatch" });
  }
  return { intact: breaks.length === 0, breaks };
}

function saveProfile(state: State, body: Record<string, string>): TenantSettings {
  const errors: Array<{ loc: string[]; msg: string; type: string }> = [];
  const required = [
    "mandt",
    "sender_port",
    "sender_partner",
    "receiver_port",
    "receiver_partner",
    "vendor_number",
    "vendor_name",
  ];
  for (const key of required) {
    if (!body[key]?.trim())
      errors.push({ loc: ["body", key], msg: "Field required", type: "missing" });
  }
  if (body.mandt && !/^\d{3}$/.test(body.mandt)) {
    errors.push({
      loc: ["body", "mandt"],
      msg: "String should match pattern '^\\d{3}$'",
      type: "string_pattern_mismatch",
    });
  }
  if (errors.length) throw new HttpError(422, errors);
  state.tenant.sap_outbound_profile = {
    docrel: "750",
    status: "30",
    direct: "1",
    sender_partner_type: "LS",
    receiver_partner_type: "LS",
    ...body,
  } as Profile;
  return state.tenant;
}

// -------------------------------------------------------------- router

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export async function handle(request: Request): Promise<Response> {
  const url = new URL(request.url, typeof location === "undefined" ? "http://demo" : location.href);
  const path = url.pathname.slice(url.pathname.indexOf("/api/v1/"));
  const method = request.method.toUpperCase();
  const body =
    method === "GET" ? null : await request.text().then((t) => (t ? JSON.parse(t) : null));
  const state = load();
  const p = url.searchParams;
  const slow = /generate-from-rfq|reparse/.test(path);
  await delay(slow ? 1200 : 60 + Math.random() * 120);

  try {
    let m: RegExpExecArray | null;
    let result: unknown;
    let write = method !== "GET";
    if (method === "GET" && path === "/api/v1/quotes") result = summaries(state, p);
    else if (method === "POST" && path === "/api/v1/quotes/generate-from-rfq")
      result = await generate(state, body);
    else if ((m = /^\/api\/v1\/quotes\/([\w-]+)$/.exec(path)) && method === "GET")
      result = refresh(state, quoteOf(state, m[1]!));
    else if (
      (m = /^\/api\/v1\/quotes\/([\w-]+)\/items\/([\w-]+)$/.exec(path)) &&
      method === "PATCH"
    )
      result = await editItem(state, m[1]!, m[2]!, body ?? {});
    else if ((m = /^\/api\/v1\/quotes\/([\w-]+)\/calculate$/.exec(path)) && method === "POST")
      result = await calculateQuote(state, m[1]!, body ?? {});
    else if ((m = /^\/api\/v1\/quotes\/([\w-]+)\/approve$/.exec(path)) && method === "POST")
      result = await approve(state, m[1]!, body?.comment ?? null);
    else if ((m = /^\/api\/v1\/quotes\/([\w-]+)\/reparse$/.exec(path)) && method === "POST")
      result = await reparse(state, m[1]!);
    else if (
      (m = /^\/api\/v1\/quotes\/([\w-]+)\/sap-idoc\/prepare$/.exec(path)) &&
      method === "POST"
    )
      result = await prepare(state, m[1]!);
    else if ((m = /^\/api\/v1\/quotes\/([\w-]+)\/sap-idoc\/send$/.exec(path)) && method === "POST")
      result = await send(state, m[1]!, body);
    else if (method === "GET" && path === "/api/v1/rfqs") result = inbox(state);
    else if (method === "GET" && path === "/api/v1/materials") {
      const q = (p.get("q") ?? "").toLowerCase();
      const type = (p.get("type") ?? "").toUpperCase();
      const rows = state.materials.filter(
        (mat) =>
          (!type || mat.material_type === type) &&
          (!q ||
            [
              mat.matnr,
              mat.description ?? "",
              ...Object.values(mat.descriptions as Record<string, string>),
            ]
              .join(" ")
              .toLowerCase()
              .includes(q)),
      );
      result = page(rows, p, 100);
    } else if (method === "GET" && path === "/api/v1/customers") {
      const q = (p.get("q") ?? "").toLowerCase();
      const rows = state.customers.filter(
        (c) => !q || [c.kunnr, c.name1, c.city ?? ""].some((v) => v.toLowerCase().includes(q)),
      );
      result = page(rows, p, 100);
    } else if (method === "GET" && path === "/api/v1/audit-logs") {
      result = [...state.audit]
        .sort((a, b) => b.seq - a.seq)
        .slice(0, Number(p.get("limit") ?? 100));
    } else if (method === "GET" && path === "/api/v1/audit-logs/verify")
      result = await verifyChain(state);
    else if (method === "GET" && path === "/api/v1/tenant") result = state.tenant;
    else if (method === "PUT" && path === "/api/v1/tenant/sap-outbound-profile")
      result = saveProfile(state, body ?? {});
    else if (method === "GET" && path === "/api/v1/sap/status") result = sapStatus(state);
    else {
      write = false;
      throw new HttpError(404, "not found (demo)");
    }
    if (write) save(state);
    return json(path.endsWith("generate-from-rfq") || path.endsWith("reparse") ? 201 : 200, result);
  } catch (error) {
    if (error instanceof HttpError) {
      memory = null; // drop half-applied changes: reload the last saved state
      return json(error.status, { detail: error.detail });
    }
    throw error;
  }
}
