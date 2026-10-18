/**
 * Optimistic copies of a quote: what the API will return after an edit or a
 * Zuschlag change, computed locally so the UI reacts before the round trip.
 * Mirrors apps/api quoting/studio.py (`edit_item`, `_rollup`) and
 * quoting/service.py (`apply_calculation`).
 */
import type { ItemUpdate, QuoteDetail, QuoteItemOut } from "@zuschlag/api-types";

import { Dec } from "@/lib/decimal";
import {
  calculate,
  lineInputs,
  MAX_ZUSCHLAG_PCT,
  type Totals,
  type VatPercent,
} from "@/lib/pricing";

export function vatOf(quote: Pick<QuoteDetail, "vat_rate">): VatPercent {
  return Dec.tryFrom(quote.vat_rate)?.eq(7) ? 7 : 19;
}

export function clampPct(value: Dec): Dec {
  if (value.isNegative()) return Dec.ZERO;
  return value.cmp(MAX_ZUSCHLAG_PCT) > 0 ? Dec.from(MAX_ZUSCHLAG_PCT) : value;
}

export function totalsFor(quote: QuoteDetail, pct?: Dec, vat?: VatPercent): Totals {
  return calculate(
    lineInputs(quote.items),
    clampPct(pct ?? Dec.from(quote.margin_pct)),
    vat ?? vatOf(quote),
  );
}

/** Write prices and totals of `t` into a copy of `quote`. */
export function withTotals(quote: QuoteDetail, t: Totals): QuoteDetail {
  const byId = new Map(t.lines.map((l) => [l.itemId, l]));
  return {
    ...quote,
    margin_pct: t.zuschlagPct.toString(),
    vat_rate: String(t.vatRate),
    material_cost: t.materialCost.toFixed(2),
    labor_cost: t.laborCost.toFixed(2),
    total_cost: t.factoryCost.toFixed(2),
    net_total: t.netAmount.toFixed(2),
    vat_amount: t.vatAmount.toFixed(2),
    gross_total: t.grossAmount.toFixed(2),
    items: quote.items.map((item) => {
      const line = byId.get(item.id);
      return {
        ...item,
        margin_pct: line ? t.zuschlagPct.toString() : null,
        unit_margin: line ? line.unitZuschlag.toFixed(4) : null,
        unit_price: line ? line.unitPrice.toFixed(4) : null,
        line_total: line ? line.netAmount.toFixed(2) : null,
      };
    }),
  };
}

const money = (d: Dec) => d.toFixed(2);

function rollup(item: QuoteItemOut): QuoteItemOut {
  const kids = item.components.map((k) => {
    const cost = Dec.tryFrom(k.unit_cost);
    return { ...k, extended_cost: cost ? money(cost.mul(k.quantity).quantize(2)) : null };
  });
  let unitCost = Dec.tryFrom(item.unit_cost);
  if (kids.length) {
    const priced = kids.every((k) => k.unit_cost !== null && k.quantity_per_parent !== null);
    unitCost = priced
      ? Dec.sum(kids.map((k) => Dec.from(k.unit_cost!).mul(k.quantity_per_parent!))).quantize(4)
      : null;
  }
  return {
    ...item,
    components: kids,
    unit_cost: unitCost ? unitCost.toFixed(4) : null,
    extended_cost: unitCost ? money(unitCost.mul(item.quantity).quantize(2)) : null,
  };
}

function patchItem(item: QuoteItemOut, patch: ItemUpdate, parentQty?: string): QuoteItemOut {
  const next: QuoteItemOut = { ...item };
  if (patch.description !== undefined && patch.description !== null)
    next.description = patch.description;
  if (patch.uom) next.uom = patch.uom.toUpperCase();
  if (patch.unit_cost !== undefined) {
    next.unit_cost =
      patch.unit_cost === null ? null : Dec.from(patch.unit_cost).quantize(4).toFixed();
  }
  if (patch.quantity) {
    const qty = Dec.from(patch.quantity).quantize(3);
    next.quantity = qty.toFixed();
    if (parentQty) next.quantity_per_parent = null; // recomputed by the server
    next.components = item.components.map((k) =>
      k.quantity_per_parent
        ? { ...k, quantity: Dec.from(k.quantity_per_parent).mul(qty).quantize(3).toFixed() }
        : k,
    );
  }
  if (patch.matnr !== undefined) {
    // Price and MAKTX come from MATMAS: shown as pending until the server answers.
    next.matnr = patch.matnr || null;
    next.match_method = "manual";
  }
  return next;
}

export function applyItemPatch(quote: QuoteDetail, itemId: string, patch: ItemUpdate): QuoteDetail {
  const items = quote.items.map((top) => {
    if (top.id === itemId) return rollup(patchItem(top, patch));
    if (top.components.some((k) => k.id === itemId)) {
      return rollup({
        ...top,
        components: top.components.map((k) =>
          k.id === itemId ? patchItem(k, patch, top.quantity) : k,
        ),
      });
    }
    return top;
  });
  // An approved revision is frozen: the edit opens the next one (server: quoting/service.py open_revision).
  const reopen = quote.status === "approved";
  const next = {
    ...quote,
    items,
    status: reopen ? ("draft" as const) : quote.status,
    revision: reopen ? quote.revision + 1 : quote.revision,
  };
  return withTotals(next, totalsFor(next));
}
