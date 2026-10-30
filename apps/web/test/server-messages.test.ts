/** API messages appear in German in the German UI; unknown ones pass through unchanged. */
import { describe, expect, it } from "vitest";

import { translate } from "@/i18n";
import { serverText } from "@/lib/server-messages";

const de = (text: string) => serverText(text, "de", translate("de"));

describe("server messages in German", () => {
  it.each([
    [
      "quote has not been calculated (Zuschlag, VAT and payment terms)",
      "Angebot ist noch nicht kalkuliert (Zuschlag, MwSt., Zahlungsbedingung)",
    ],
    ["Item 00020: SAP match needs human review", "Pos. 00020: SAP-Zuordnung muss geprüft werden"],
    ["Item 10.3: SAP match needs human review", "Pos. 10.3: SAP-Zuordnung muss geprüft werden"],
    [
      "quote is draft; it must be approved before ERP sync",
      "Angebot ist „Entwurf“ – vor dem SAP-Sync freigeben",
    ],
    ["Item 10: no price available", "Pos. 10: kein Preis verfügbar"],
    [
      "Item 20 'Lochblech 1.4301, 1,5 mm, Rundloch R5T8': not found in SAP catalog (missing material)",
      "Pos. 20 „Lochblech 1.4301, 1,5 mm, Rundloch R5T8“: nicht im SAP-Katalog gefunden",
    ],
    [
      "Item 10 'Rollen': match PT-CAS-125HD has confidence 0.62 (NEEDS_HUMAN_REVIEW)",
      "Pos. 10 „Rollen“: Zuordnung PT-CAS-125HD nur mit Konfidenz 0,62 – bitte prüfen",
    ],
    ["Open question: Oberfläche geschliffen?", "Offene Frage: Oberfläche geschliffen?"],
    ["customer 999999 not found", "Kunde 999999 nicht gefunden"],
    [
      "material XYZ-123 not found in the SAP material master (MATMAS)",
      "Material XYZ-123 ist nicht im SAP-Materialstamm (MATMAS)",
    ],
    [
      "payment terms NT60 deviate from the customer's agreed terms NT30 (set allow_terms_deviation to override)",
      "Zahlungsbedingung NT60 weicht von der vereinbarten Kondition NT30 ab („Abweichung erlauben“ aktivieren)",
    ],
    ["mandt: String should match pattern '^\\d{3}$'", "Mandant (MANDT): ungültiges Format"],
    ["vendor_name: Field required", "Eigener Name: Pflichtfeld"],
    [
      "SAP rejected the IDoc (status 51): Auftraggeber unbekannt",
      "SAP hat das IDoc abgelehnt (Status 51): Auftraggeber unbekannt",
    ],
  ])("%s", (english, german) => {
    expect(de(english)).toBe(german);
  });

  it("translates each part of a combined message", () => {
    expect(de("Item 10: not priced; quote has no items")).toBe(
      "Pos. 10: ohne Preis; Angebot hat keine Positionen",
    );
  });

  it("leaves unknown messages and German text untouched", () => {
    expect(de("Demo: keine Positionen erkannt.")).toBe("Demo: keine Positionen erkannt.");
    expect(de("Something new from the server")).toBe("Something new from the server");
  });

  it("does nothing in English", () => {
    expect(serverText("customer 1 not found", "en", translate("en"))).toBe("customer 1 not found");
  });
});
