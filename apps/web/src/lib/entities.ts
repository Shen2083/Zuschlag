/**
 * Locate the entities the AI extracted (customer, contact, items, specs, dates)
 * in the raw inquiry text so the estimator can check them against the source.
 * Only verbatim (case-insensitive) occurrences are highlighted; anything the
 * model paraphrased is listed as "not verbatim in text" rather than guessed.
 */
import type { MessageKey } from "@/i18n";

export type EntityKind = "party" | "item" | "spec" | "date";

export interface Entity {
  id: string;
  kind: EntityKind;
  label: MessageKey;
  text: string;
  /** Where the text was found; empty if not verbatim. */
  ranges: Array<[number, number]>;
}

export interface Segment {
  text: string;
  entity?: Entity;
}

interface Extraction {
  customer?: Record<string, string | null | undefined>;
  line_items?: Array<{
    position?: number;
    description?: string;
    material_number?: string | null;
    quantity?: number;
    specs?: Array<{ name?: string; value?: string; unit?: string | null }>;
  }>;
  open_questions?: string[];
}

function occurrences(haystack: string, needle: string): Array<[number, number]> {
  const out: Array<[number, number]> = [];
  if (needle.trim().length < 2) return out;
  const h = haystack.toLocaleLowerCase("de");
  const n = needle.trim().toLocaleLowerCase("de");
  for (let i = h.indexOf(n); i !== -1; i = h.indexOf(n, i + n.length)) out.push([i, i + n.length]);
  return out;
}

export function findEntities(extraction: unknown, body: string): Entity[] {
  const ex = (extraction ?? {}) as Extraction;
  const raw: Array<Omit<Entity, "id" | "ranges">> = [];
  const add = (kind: EntityKind, label: MessageKey, text: string | null | undefined) => {
    if (text && text.trim()) raw.push({ kind, label, text: text.trim() });
  };
  const c = ex.customer ?? {};
  add("party", "studio.entity.company", c.company_name);
  add("party", "studio.entity.contact", c.contact_name);
  add("party", "studio.entity.email", c.contact_email);
  add("party", "studio.entity.phone", c.contact_phone);
  add("party", "studio.entity.reference", c.customer_reference);
  add("date", "studio.entity.delivery", c.delivery_date_text);
  for (const line of ex.line_items ?? []) {
    add("item", "studio.entity.item", line.description);
    add("item", "studio.entity.material", line.material_number);
    for (const spec of line.specs ?? []) {
      // "250 kg" may be written "250kg" or "250 kg": try both, then the bare value.
      const value = spec.value ?? "";
      const withUnit = spec.unit ? [`${value} ${spec.unit}`, `${value}${spec.unit}`] : [];
      const hit = [...withUnit, value].find((v) => occurrences(body, v).length);
      add("spec", "studio.entity.spec", hit ?? (withUnit[0] || value));
    }
  }

  const seen = new Set<string>();
  const taken: Array<[number, number]> = [];
  const overlaps = ([a, b]: [number, number]) => taken.some(([x, y]) => a < y && x < b);
  // Longest first, so "Edelstahlblech 1.4301" wins over "1.4301".
  return raw
    .filter(
      (e) =>
        !seen.has(`${e.kind}:${e.text.toLowerCase()}`) &&
        seen.add(`${e.kind}:${e.text.toLowerCase()}`),
    )
    .sort((a, b) => b.text.length - a.text.length)
    .map((e, i) => {
      const ranges = occurrences(body, e.text).filter((r) => !overlaps(r));
      taken.push(...ranges);
      return { ...e, id: `entity-${i}`, ranges };
    });
}

export function segments(body: string, entities: Entity[]): Segment[] {
  const marks = entities
    .flatMap((entity) => entity.ranges.map(([start, end]) => ({ start, end, entity })))
    .sort((a, b) => a.start - b.start);
  const out: Segment[] = [];
  let cursor = 0;
  for (const m of marks) {
    if (m.start > cursor) out.push({ text: body.slice(cursor, m.start) });
    out.push({ text: body.slice(m.start, m.end), entity: m.entity });
    cursor = m.end;
  }
  if (cursor < body.length) out.push({ text: body.slice(cursor) });
  return out;
}
