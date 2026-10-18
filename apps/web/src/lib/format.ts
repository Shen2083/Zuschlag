/**
 * Locale-aware formatting of exact decimals: de-DE renders 1250.5 EUR as
 * "1.250,50 €". Separators and the currency pattern come from Intl, the digits
 * from the decimal string itself, so no amount ever passes through a float.
 */
import { Dec, type DecimalLike } from "@/lib/decimal";

export type Locale = "de" | "en";
export const INTL_LOCALE: Record<Locale, string> = { de: "de-DE", en: "en-GB" };

interface Symbols {
  group: string;
  decimal: string;
}

const symbolCache = new Map<string, Symbols>();

function symbols(locale: Locale): Symbols {
  const tag = INTL_LOCALE[locale];
  let s = symbolCache.get(tag);
  if (!s) {
    const parts = new Intl.NumberFormat(tag).formatToParts(12345.6);
    s = {
      group: parts.find((p) => p.type === "group")?.value ?? ".",
      decimal: parts.find((p) => p.type === "decimal")?.value ?? ",",
    };
    symbolCache.set(tag, s);
  }
  return s;
}

function digits(value: Dec, minFrac: number, maxFrac: number, locale: Locale): string {
  const { group, decimal } = symbols(locale);
  let fixed = value.quantize(maxFrac).toFixed();
  const negative = fixed.startsWith("-");
  if (negative) fixed = fixed.slice(1);
  let [int = "0", frac = ""] = fixed.split(".");
  frac = frac.replace(/0+$/, "").padEnd(minFrac, "0");
  int = int.replace(/\B(?=(\d{3})+(?!\d))/g, group);
  const zero = /^[0.,\s]*$/.test(int + frac);
  return `${negative && !zero ? "−" : ""}${int}${frac ? decimal + frac : ""}`;
}

export function formatNumber(
  value: DecimalLike | null | undefined,
  locale: Locale,
  { minFrac = 0, maxFrac = 3 }: { minFrac?: number; maxFrac?: number } = {},
): string {
  const d = Dec.tryFrom(value);
  return d ? digits(d, minFrac, maxFrac, locale) : "—";
}

/** "1.250,50 €" (de) / "€1,250.50" (en). `places` = 4 for unit prices. */
export function formatMoney(
  value: DecimalLike | null | undefined,
  currency: string,
  locale: Locale,
  { places = 2, minPlaces = 2 }: { places?: number; minPlaces?: number } = {},
): string {
  const d = Dec.tryFrom(value);
  if (!d) return "—";
  const number = digits(d, minPlaces, places, locale);
  let pattern: Intl.NumberFormatPart[];
  try {
    pattern = new Intl.NumberFormat(INTL_LOCALE[locale], {
      style: "currency",
      currency,
    }).formatToParts(1);
  } catch {
    return `${number} ${currency}`;
  }
  let out = "";
  let placed = false;
  for (const part of pattern) {
    if (["integer", "group", "decimal", "fraction"].includes(part.type)) {
      if (!placed) out += number;
      placed = true;
    } else {
      out += part.value;
    }
  }
  return out;
}

export function formatPercent(value: DecimalLike | null | undefined, locale: Locale, maxFrac = 2) {
  const d = Dec.tryFrom(value);
  return d ? `${digits(d, 0, maxFrac, locale)} %` : "—";
}

/**
 * Parse what an estimator types: "1.250,5", "22,5" or "22.5" (de), "1,250.5" (en).
 * Returns a canonical decimal string ("1250.5") or null.
 */
export function parseDecimalInput(input: string, locale: Locale): string | null {
  let s = input
    .trim()
    .replace(/[\s  %€]/g, "")
    .replace("−", "-");
  if (!s) return null;
  if (locale === "de") {
    if (s.includes(",")) s = s.replace(/\./g, "").replace(",", ".");
    else if ((s.match(/\./g) ?? []).length > 1 || /\.\d{3}$/.test(s)) s = s.replace(/\./g, "");
  } else {
    s = s.replace(/,/g, "");
  }
  const d = Dec.tryFrom(s);
  return d && /^-?\d*\.?\d*$/.test(s) ? d.toString() : null;
}

/** Decimal string formatted for an <input> the user will edit ("22,5"). */
export function decimalForInput(value: DecimalLike | null | undefined, locale: Locale): string {
  const d = Dec.tryFrom(value);
  if (!d) return "";
  const s = d.toString();
  return locale === "de" ? s.replace(".", ",") : s;
}

export function formatDateTime(iso: string | null | undefined, locale: Locale): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(INTL_LOCALE[locale], {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Europe/Berlin",
  }).format(new Date(iso));
}

export function formatDate(iso: string | null | undefined, locale: Locale): string {
  if (!iso) return "—";
  // Plain dates ("2026-11-27") are calendar days: format without a time-zone shift.
  const date = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? new Date(`${iso}T12:00:00Z`) : new Date(iso);
  return new Intl.DateTimeFormat(INTL_LOCALE[locale], {
    dateStyle: "medium",
    timeZone: "Europe/Berlin",
  }).format(date);
}

/** SAP-style item number: 10 -> "00010". */
export const posex = (position: number) => String(position).padStart(5, "0");
