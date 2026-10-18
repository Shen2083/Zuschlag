/**
 * Browser mirror of the API's Zuschlagskalkulation (apps/api quoting/calculation.py
 * and quoting/service.py `line_inputs`), so the Zuschlag slider updates line prices,
 * VAT and totals instantly. The server recalculates authoritatively on commit; the
 * unit tests pin both implementations to the same reference figures.
 *
 *   Materialkosten + Fertigungslohn = Herstellkosten
 *   per unit: Zuschlag = round4(unit cost x %), price = round4(unit cost + Zuschlag)
 *   line net = round2(price x quantity); VAT once on the net total
 */
import type { QuoteItemOut } from "@zuschlag/api-types";

import { Dec, type DecimalLike } from "@/lib/decimal";

export type VatPercent = 19 | 7;

export interface LineInput {
  itemId: string;
  position: number;
  quantity: DecimalLike;
  /** Herstellkosten per unit; null = not priceable yet */
  unitCost: DecimalLike | null;
  materialCost: DecimalLike;
  laborCost: DecimalLike;
}

export interface LineResult {
  itemId: string;
  position: number;
  unitCost: Dec;
  unitZuschlag: Dec;
  unitPrice: Dec;
  netAmount: Dec;
  factoryCost: Dec;
}

export interface Totals {
  zuschlagPct: Dec;
  vatRate: VatPercent;
  lines: LineResult[];
  missingPricePositions: number[];
  materialCost: Dec;
  laborCost: Dec;
  factoryCost: Dec;
  zuschlagAmount: Dec;
  netAmount: Dec;
  vatAmount: Dec;
  grossAmount: Dec;
}

export const MAX_ZUSCHLAG_PCT = 100;
const money = (d: Dec) => d.quantize(2);
const unitAmount = (d: Dec) => d.quantize(4);

export function priceLine(unitCost: DecimalLike, quantity: DecimalLike, pct: DecimalLike) {
  const cost = Dec.from(unitCost);
  const unitZuschlag = unitAmount(cost.mul(pct).shift(2));
  const unitPrice = unitAmount(cost.add(unitZuschlag));
  return {
    unitCost: unitAmount(cost),
    unitZuschlag,
    unitPrice,
    lineTotal: money(unitPrice.mul(quantity)),
  };
}

export function calculate(
  lines: LineInput[],
  zuschlagPct: DecimalLike,
  vatRate: VatPercent,
): Totals {
  const pct = Dec.from(zuschlagPct);
  if (pct.isNegative() || pct.cmp(MAX_ZUSCHLAG_PCT) > 0) {
    throw new RangeError("Zuschlag must be between 0 and 100 percent");
  }
  const results: LineResult[] = [];
  const missing: number[] = [];
  for (const line of [...lines].sort((a, b) => a.position - b.position)) {
    if (line.unitCost === null) {
      missing.push(line.position);
      continue;
    }
    const priced = priceLine(line.unitCost, line.quantity, pct);
    results.push({
      itemId: line.itemId,
      position: line.position,
      unitCost: priced.unitCost,
      unitZuschlag: priced.unitZuschlag,
      unitPrice: priced.unitPrice,
      netAmount: priced.lineTotal,
      factoryCost: money(Dec.from(line.materialCost).add(line.laborCost)),
    });
  }
  const materialCost = money(
    Dec.sum(lines.filter((l) => l.unitCost !== null).map((l) => money(Dec.from(l.materialCost)))),
  );
  const laborCost = money(
    Dec.sum(lines.filter((l) => l.unitCost !== null).map((l) => money(Dec.from(l.laborCost)))),
  );
  const factoryCost = money(materialCost.add(laborCost));
  const netAmount = money(Dec.sum(results.map((r) => r.netAmount)));
  const vatAmount = money(netAmount.mul(vatRate).shift(2));
  return {
    zuschlagPct: pct,
    vatRate,
    lines: results,
    missingPricePositions: missing,
    materialCost,
    laborCost,
    factoryCost,
    zuschlagAmount: money(netAmount.sub(factoryCost)),
    netAmount,
    vatAmount,
    grossAmount: money(netAmount.add(vatAmount)),
  };
}

type Item = Pick<
  QuoteItemOut,
  "id" | "position" | "kind" | "quantity" | "unit_cost" | "extended_cost" | "components"
>;

/** Top-level BOM lines with Herstellkosten split into material and labor. */
export function lineInputs(items: Item[]): LineInput[] {
  return items.map((item) => {
    const kids = item.components ?? [];
    let material: Dec;
    let labor: Dec;
    if (kids.length) {
      const cost = (k: Item) => Dec.tryFrom(k.extended_cost) ?? Dec.ZERO;
      labor = Dec.sum(kids.filter((k) => k.kind === "labor").map(cost));
      material = Dec.sum(kids.filter((k) => k.kind !== "labor").map(cost));
    } else {
      const total = money((Dec.tryFrom(item.unit_cost) ?? Dec.ZERO).mul(item.quantity));
      labor = item.kind === "labor" ? total : Dec.ZERO;
      material = item.kind === "labor" ? Dec.ZERO : total;
    }
    return {
      itemId: item.id,
      position: item.position,
      quantity: item.quantity,
      unitCost: item.unit_cost ?? null,
      materialCost: material,
      laborCost: labor,
    };
  });
}
