/**
 * German renderings of the messages the API returns (approval and export
 * blockers, AI review notes, validation and SAP errors). The API speaks
 * English; the estimator reads German. Anything not in this catalogue is
 * shown as sent, so a new server message is never hidden.
 */
import { useCallback } from "react";

import { useI18n, type Translate } from "@/i18n";
import type { Locale } from "@/lib/format";

type Rule = [RegExp, (m: RegExpMatchArray, t: Translate) => string];

const STATUS: Record<string, string> = {
  draft: "status.draft",
  needs_review: "status.needs_review",
  approved: "status.approved",
  synced: "status.synced",
};

const FIELD_LABELS: Record<string, string> = {
  mandt: "Mandant (MANDT)",
  docrel: "Release (DOCREL)",
  sender_port: "Senderport",
  sender_partner: "Senderpartner",
  receiver_port: "Empfängerport",
  receiver_partner: "Empfängerpartner",
  vendor_number: "Eigene Lieferantennr.",
  vendor_name: "Eigener Name",
  zuschlag_pct: "Zuschlag",
  vat_rate: "MwSt.",
  payment_terms: "Zahlungsbedingung",
  quantity: "Menge",
  unit_cost: "Basiskosten",
  uom: "Einheit",
  description: "Bezeichnung",
  matnr: "Materialnummer",
  raw_text: "Anfragetext",
  customer_id: "Kunde",
};

function validation(msg: string): string {
  const max = /at most (\d+) characters/.exec(msg);
  if (/Field required/.test(msg)) return "Pflichtfeld";
  if (/should match pattern/.test(msg)) return "ungültiges Format";
  if (max) return `höchstens ${max[1]} Zeichen`;
  if (/at least 1 character/.test(msg)) return "darf nicht leer sein";
  if (/greater than (or equal to )?0/.test(msg)) return "muss größer als 0 sein";
  if (/valid (decimal|number)/.test(msg)) return "keine gültige Zahl";
  if (/Input should be/.test(msg)) return "ungültiger Wert";
  return msg;
}

const RULES: Rule[] = [
  // approval / export blockers
  [/^quote is already synced to SAP$/, () => "Angebot wurde bereits an SAP übertragen"],
  [
    /^quote (\S+) is already synced to SAP$/,
    (m) => `Angebot ${m[1]} wurde bereits an SAP übertragen`,
  ],
  [
    /^quote has not been calculated \(Zuschlag, VAT and payment terms\)$/,
    () => "Angebot ist noch nicht kalkuliert (Zuschlag, MwSt., Zahlungsbedingung)",
  ],
  [
    /^quote has not been calculated \(no payment terms\); call \/calculate first$/,
    () => "Angebot ist noch nicht kalkuliert (keine Zahlungsbedingung)",
  ],
  [/^quote has no items$/, () => "Angebot hat keine Positionen"],
  [
    /^Item ([\d.]+): SAP match needs human review$/,
    (m) => `Pos. ${m[1]}: SAP-Zuordnung muss geprüft werden`,
  ],
  [/^Item ([\d.]+): not priced$/, (m) => `Pos. ${m[1]}: ohne Preis`],
  [
    /^quote is (\w+); it must be approved before ERP sync$/,
    (m, t) =>
      `Angebot ist „${STATUS[m[1]!] ? t(STATUS[m[1]!] as never) : m[1]}“ – vor dem SAP-Sync freigeben`,
  ],
  [
    /^tenant has no SAP outbound partner profile/,
    () => "Kein SAP-Partnerprofil (Ausgang) hinterlegt (Einstellungen)",
  ],
  [
    /^quote is not linked to an SAP customer \(KUNNR\)$/,
    () => "Angebot ist keinem SAP-Kunden (KUNNR) zugeordnet",
  ],
  [
    /^Item ([\d.]+): no SAP material number \(custom build or missing in catalog\)$/,
    (m) => `Pos. ${m[1]}: keine SAP-Materialnummer (Sonderanfertigung oder nicht im Katalog)`,
  ],
  [
    /^Item ([\d.]+): SAP match (\S+) is NEEDS_HUMAN_REVIEW$/,
    (m) => `Pos. ${m[1]}: SAP-Zuordnung ${m[2]} muss geprüft werden`,
  ],
  // AI review notes
  [/^Item ([\d.]+): no price available$/, (m) => `Pos. ${m[1]}: kein Preis verfügbar`],
  [
    /^Item ([\d.]+): AI-proposed BOM and labor for custom build must be confirmed; a new SAP material \(FERT\) is needed before ERP sync$/,
    (m) =>
      `Pos. ${m[1]}: KI-Stückliste und Arbeitsgänge der Sonderanfertigung bestätigen; vor dem SAP-Sync ist ein neues SAP-Material (FERT) nötig`,
  ],
  [
    /^Item ([\d.]+) '(.*)': not found in SAP catalog \(missing material\)$/,
    (m) => `Pos. ${m[1]} „${m[2]}“: nicht im SAP-Katalog gefunden`,
  ],
  [
    /^Item ([\d.]+) '(.*)': match (\S+) has confidence ([\d.]+) \(NEEDS_HUMAN_REVIEW\)$/,
    (m) =>
      `Pos. ${m[1]} „${m[2]}“: Zuordnung ${m[3]} nur mit Konfidenz ${m[4]!.replace(".", ",")} – bitte prüfen`,
  ],
  [
    /^Item ([\d.]+): no fabrication labor estimated for custom build$/,
    (m) => `Pos. ${m[1]}: keine Fertigungszeiten geschätzt`,
  ],
  [
    /^Component ([\d.]+): material (\S+) has no price in SAP$/,
    (m) => `Komponente ${m[1]}: Material ${m[2]} hat keinen SAP-Preis`,
  ],
  [
    /^Customer '(.*)' not found in SAP customer master$/,
    (m) => `Kunde „${m[1]}“ nicht im SAP-Kundenstamm`,
  ],
  [/^Open question: (.*)$/, (m) => `Offene Frage: ${m[1]}`],
  // edits
  [
    /^material (\S+) not found in the SAP material master \(MATMAS\)$/,
    (m) => `Material ${m[1]} ist nicht im SAP-Materialstamm (MATMAS)`,
  ],
  [/^material (\S+) is inactive in SAP$/, (m) => `Material ${m[1]} ist in SAP gesperrt`],
  [/^labor operations have no SAP material$/, () => "Arbeitsgänge haben kein SAP-Material"],
  [/^description must not be empty$/, () => "Die Bezeichnung darf nicht leer sein"],
  [/^unit must be an ISO unit code/, () => "Einheit muss ein ISO-Code wie PCE, KGM oder HUR sein"],
  [
    /^the cost of a custom build is rolled up from its components$/,
    () => "Die Kosten einer Sonderanfertigung ergeben sich aus ihren Komponenten",
  ],
  [/^unit cost must not be negative$/, () => "Kosten dürfen nicht negativ sein"],
  [/^quantity must be greater than zero$/, () => "Die Menge muss größer als 0 sein"],
  [/^nothing to change$/, () => "Keine Änderung"],
  // payment terms
  [
    /^payment terms (\S+) deviate from the customer's agreed terms (.+) \(set allow_terms_deviation to override\)$/,
    (m) =>
      `Zahlungsbedingung ${m[1]} weicht von der vereinbarten Kondition ${m[2]} ab („Abweichung erlauben“ aktivieren)`,
  ],
  [
    /^unknown payment terms '(.*)'/,
    (m) => `Unbekannte Zahlungsbedingung „${m[1]}“ – bitte NT<Tage> verwenden, z. B. NT30`,
  ],
  [/^invalid payment terms key/, () => "Ungültige Zahlungsbedingung (1–4 Zeichen, z. B. NT30)"],
  // quotes, customers, RFQs
  [/^quote (\S+) not found$/, () => "Angebot nicht gefunden"],
  [/^customer (\S+) not found$/, (m) => `Kunde ${m[1]} nicht gefunden`],
  [/^item (\S+) not found$/, () => "Position nicht gefunden"],
  [
    /^quote has no source RFQ text to re-parse$/,
    () => "Zu diesem Angebot ist kein Anfragetext gespeichert",
  ],
  [/^LLM extraction is not configured/, () => "Die KI-Extraktion ist nicht konfiguriert"],
  [/^LLM extraction failed/, () => "Die KI-Extraktion ist fehlgeschlagen"],
  [/^embedding backend unavailable$/, () => "Der Katalogabgleich ist gerade nicht verfügbar"],
  // SAP
  [/^quote not ready for SAP$/, () => "Angebot ist noch nicht bereit für SAP"],
  [/^quote cannot be approved yet$/, () => "Angebot kann noch nicht freigegeben werden"],
  [
    /^IDoc (\d+) was not prepared for this quote$/,
    (m) => `IDoc ${m[1]} wurde für dieses Angebot nicht erzeugt`,
  ],
  [
    /^the quote changed after the IDoc preview/,
    () => "Das Angebot wurde nach der Vorschau geändert – bitte neue Vorschau prüfen",
  ],
  [
    /^SAP rejected the IDoc \(status 51\): (.*)$/,
    (m) => `SAP hat das IDoc abgelehnt (Status 51): ${m[1]}`,
  ],
  [/^SAP endpoint unreachable/, () => "SAP ist nicht erreichbar"],
  [/^SAP endpoint answered HTTP (\d+)$/, (m) => `SAP hat mit HTTP ${m[1]} geantwortet`],
  [/^no SAP outbound transport configured/, () => "Kein SAP-Ausgangskanal konfiguriert"],
  [/^Zuschlag API unreachable$/, () => "Die Zuschlag-API ist nicht erreichbar"],
  [/^cross-site request refused$/, () => "Anfrage abgelehnt (fremde Herkunft)"],
  [/^HTTP (\d+)$/, (m) => `Serverfehler (HTTP ${m[1]})`],
  // field validation from the API ("mandt: String should match pattern ...")
  [/^(\w+): (.+)$/, (m) => `${FIELD_LABELS[m[1]!] ?? m[1]}: ${validation(m[2]!)}`],
];

function translateOne(text: string, t: Translate): string | null {
  for (const [pattern, render] of RULES) {
    const m = text.match(pattern);
    if (m) return render(m, t);
  }
  return null;
}

export function serverText(text: string, locale: Locale, t: Translate): string {
  if (locale !== "de") return text;
  // Some messages contain "; " themselves; only unknown text is split into parts.
  return (
    translateOne(text, t) ??
    text
      .split("; ")
      .map((part) => translateOne(part, t) ?? part)
      .join("; ")
  );
}

/** `tr(message)`: a server message in the current UI language. */
export function useServerText(): (text: string) => string {
  const { locale, t } = useI18n();
  return useCallback((text: string) => serverText(text, locale, t), [locale, t]);
}
