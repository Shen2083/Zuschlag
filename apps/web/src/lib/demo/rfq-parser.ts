/**
 * The demo's stand-in for the AI extraction: no model runs in the static demo,
 * so new inquiries are read by this small parser. It recognises
 * "<quantity> <unit> <description>" anywhere in the text (several per
 * sentence) and matches each description against the catalog like the
 * backend's lexical signal: trigram overlap (pg_trgm style), with the same
 * review threshold (0.75) and an ambiguity check.
 */
export interface ParsedLine {
  quantity: string; // decimal string
  unit: string; // ISO code
  description: string;
}

export interface CatalogEntry {
  matnr: string;
  description: string | null;
  descriptions: Record<string, string>;
  is_active: boolean;
}

export interface Match<T extends CatalogEntry> {
  material: T | null;
  confidence: number;
  method: "exact_text" | "exact" | "lexical" | "none";
  ambiguous: boolean;
}

const UNIT_WORDS: Array<[RegExp, string]> = [
  [/^(stück|stueck|stk|st|pcs|pc|pieces?|units?|teile?)$/i, "PCE"],
  [/^(sätze?|saetze?|sets?)$/i, "SET"],
  [/^(paare?|pairs?)$/i, "PR"],
  [/^(kg|kilo(gramm)?)$/i, "KGM"],
  [/^(meter|metre|lfm|lfdm)$/i, "MTR"],
  [/^(m2|m²|qm)$/i, "MTK"],
  [/^(std|stunden?|hours?|h)$/i, "HUR"],
];
const UNIT_PATTERN =
  "stück|stueck|stk|st|pcs|pc|pieces?|units?|teile?|sätze?|saetze?|sets?|paare?|pairs?|kg|kilogramm|kilo|meter|metre|lfm|lfdm|m2|m²|qm|std|stunden?|hours?";
const ITEM = new RegExp(
  `(?<![\\w.,])(\\d+(?:[.,]\\d+)?)\\s*(${UNIT_PATTERN})\\.?(?=[\\s:,;]|$)`,
  "giu",
);
const LEAD = /^(?:[à:\-–]|x|of|von|des|der|die|das|à)\s+/i;
// Connecting words between items ("..., dazu 25 Stück ...") are not part of a description.
const TRAIL =
  /(?:[\s,;:.!?]+|\s+(?:und|and|sowie|plus|dazu|außerdem|ausserdem|zusätzlich|ferner|weiterhin|also|noch|bitte|danke|thanks|please|ca\.?))+$/i;

export function parseLines(text: string): ParsedLine[] {
  const hits = [...text.matchAll(ITEM)];
  return hits
    .map((m, i) => {
      const start = m.index! + m[0].length;
      const lineEnd = text.indexOf("\n", start);
      const nextItem = hits[i + 1]?.index ?? text.length;
      const end = Math.min(lineEnd === -1 ? text.length : lineEnd, nextItem);
      let description = text.slice(start, end).trim();
      description = description.replace(LEAD, "").replace(TRAIL, "").trim();
      const unit = UNIT_WORDS.find(([re]) => re.test(m[2]!))?.[1] ?? "PCE";
      return { quantity: m[1]!.replace(",", "."), unit, description };
    })
    .filter((line) => /\p{L}{3}/u.test(line.description));
}

// ------------------------------------------------------------------ matching

const normalize = (s: string) =>
  s.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/ß/g, "ss");

function words(s: string): string[] {
  return normalize(s)
    .split(/[^a-z0-9]+/)
    .filter((w) => w.length > 1);
}

function trigrams(s: string): Set<string> {
  const out = new Set<string>();
  for (const w of words(s)) {
    const padded = `  ${w} `;
    for (let i = 0; i < padded.length - 2; i++) out.add(padded.slice(i, i + 3));
  }
  return out;
}

/** Share of the query's trigrams found in the target (like pg_trgm word_similarity). */
export function coverage(query: string, target: string): number {
  const q = trigrams(query);
  if (!q.size) return 0;
  const t = trigrams(target);
  let hit = 0;
  for (const g of q) if (t.has(g)) hit++;
  return hit / q.size;
}

const REVIEW_THRESHOLD = 0.75;
const LINK_FLOOR = 0.5;

export function bestMatch<T extends CatalogEntry>(description: string, catalog: T[]): Match<T> {
  const active = catalog.filter((m) => m.is_active);
  const texts = (m: T) => [m.description ?? "", ...Object.values(m.descriptions)].filter(Boolean);
  const wanted = normalize(description).replace(/\s+/g, " ").trim();

  const exactText = active.filter((m) =>
    texts(m).some((t) => normalize(t).replace(/\s+/g, " ").trim() === wanted),
  );
  if (exactText.length) {
    return {
      material: exactText[0]!,
      confidence: 0.97,
      method: "exact_text",
      ambiguous: exactText.length > 1,
    };
  }
  const tokens = new Set(
    (description.match(/[A-Za-z0-9][A-Za-z0-9._/-]{3,39}/g) ?? []).map((t) => t.toUpperCase()),
  );
  const cited = active.find((m) => /\d/.test(m.matnr) && tokens.has(m.matnr.toUpperCase()));
  if (cited) return { material: cited, confidence: 0.95, method: "exact", ambiguous: false };

  const scored = active
    .map((m) => ({
      m,
      score: Math.max(...texts(m).map((t) => coverage(description, `${m.matnr} ${t}`))),
    }))
    .sort((a, b) => b.score - a.score);
  const [best, second] = scored;
  if (!best || best.score < LINK_FLOOR) {
    return {
      material: null,
      confidence: Math.round((best?.score ?? 0) * 100) / 100,
      method: "none",
      ambiguous: false,
    };
  }
  const ambiguous = !!second && best.score - second.score < 0.05;
  // Lexical evidence alone stays below the confidence of an exact hit.
  const confidence = Math.round(Math.min(0.9, best.score) * 100) / 100;
  return { material: best.m, confidence, method: "lexical", ambiguous };
}

export function matchStatus(match: Match<CatalogEntry>): "MATCHED" | "NEEDS_HUMAN_REVIEW" {
  return match.material && match.confidence >= REVIEW_THRESHOLD && !match.ambiguous
    ? "MATCHED"
    : "NEEDS_HUMAN_REVIEW";
}
