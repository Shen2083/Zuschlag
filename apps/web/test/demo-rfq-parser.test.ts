/** The demo's local inquiry reader: items per sentence, fuzzy catalog matching. */
import { describe, expect, it } from "vitest";

import seed from "@/lib/demo/seed.json";
import { bestMatch, matchStatus, parseLines, type CatalogEntry } from "@/lib/demo/rfq-parser";

const CATALOG = seed.materials as unknown as CatalogEntry[];
const match = (d: string) => {
  const m = bestMatch(d, CATALOG);
  return [m.material?.matnr ?? null, matchStatus(m), m.method] as const;
};

describe("parseLines", () => {
  it("reads the sample inquiry", () => {
    expect(
      parseLines("Bitte senden Sie uns ein Angebot für 100 Stück Shen AI Product Description"),
    ).toEqual([{ quantity: "100", unit: "PCE", description: "Shen AI Product Description" }]);
  });

  it("splits several items in one sentence", () => {
    expect(
      parseLines(
        "Wir brauchen 20 Stück Schwerlastrollen mit Bremse und 5 Stück Scharniere Edelstahl.",
      ),
    ).toEqual([
      { quantity: "20", unit: "PCE", description: "Schwerlastrollen mit Bremse" },
      { quantity: "5", unit: "PCE", description: "Scharniere Edelstahl" },
    ]);
  });

  it("drops connecting words between items", () => {
    expect(
      parseLines(
        "5 Stück Scharniere Edelstahl, dazu 25 Stück Shen AI Product Description sowie 2 Sets Lüfter",
      ).map((l) => l.description),
    ).toEqual(["Scharniere Edelstahl", "Shen AI Product Description", "Lüfter"]);
  });

  it("reads lists, units and decimal commas", () => {
    const text =
      "Hallo,\n- 40 Stk. Lenkrollen 125 mm\n- 12,5 kg Edelstahlblech 1.4301\n- 3 Std Montage\nDanke";
    expect(parseLines(text)).toEqual([
      { quantity: "40", unit: "PCE", description: "Lenkrollen 125 mm" },
      { quantity: "12.5", unit: "KGM", description: "Edelstahlblech 1.4301" },
      { quantity: "3", unit: "HUR", description: "Montage" },
    ]);
  });

  it("does not take dimensions or material grades for quantities", () => {
    expect(parseLines("Racks 600 x 1000 x 2000 mm aus 1.4301")).toEqual([]);
  });

  it("reads English", () => {
    expect(parseLines("Please quote 2 pieces stainless steel work table 1200 x 700 mm")).toEqual([
      { quantity: "2", unit: "PCE", description: "stainless steel work table 1200 x 700 mm" },
    ]);
  });
});

describe("bestMatch", () => {
  it("exact SAP short text", () => {
    expect(match("Shen AI Product Description")).toEqual(["shenai", "MATCHED", "exact_text"]);
  });

  it("cited material number", () => {
    expect(match("Rollen PT-CAS-125HD")).toEqual(["PT-CAS-125HD", "MATCHED", "exact"]);
  });

  it("plurals and compounds", () => {
    expect(match("Schwerlastrollen mit Bremse")[0]).toBe("PT-CAS-125HD");
    expect(match("Scharniere Edelstahl")[0]).toBe("PT-HNG-SS180");
    expect(match("Edelstahl Arbeitstisch")[0]).toBe("FG-WT-1200");
  });

  it("weak evidence goes to review, nonsense finds nothing", () => {
    expect(match("Lochblech 1.4301")[1]).toBe("NEEDS_HUMAN_REVIEW");
    expect(match("Hydraulikzylinder")).toEqual([null, "NEEDS_HUMAN_REVIEW", "none"]);
  });
});
