/**
 * The browser recalculation must agree with the API to the cent. The reference
 * figures are the ones apps/api/tests/test_quote_calculation.py pins for the server.
 */
import { describe, expect, it } from "vitest";

import { Dec } from "@/lib/decimal";
import { calculate, lineInputs, priceLine, type LineInput } from "@/lib/pricing";

const CASTORS: LineInput = {
  itemId: "c",
  position: 10,
  quantity: "40",
  unitCost: "38.90",
  materialCost: "1556.00",
  laborCost: "0",
};
const RACKS: LineInput = {
  itemId: "r",
  position: 20,
  quantity: "15",
  unitCost: "2311.50",
  materialCost: "22215.00",
  laborCost: "12457.50",
};

describe("Zuschlagskalkulation (mirror of quoting/calculation.py)", () => {
  it("Herstellkosten -> Zuschlag -> Netto -> MwSt 19 % -> Brutto", () => {
    const c = calculate([RACKS, CASTORS], "22", 19);
    expect(c.lines.map((l) => l.position)).toEqual([10, 20]);
    expect(c.materialCost.toFixed()).toBe("23771.00");
    expect(c.laborCost.toFixed()).toBe("12457.50");
    expect(c.factoryCost.toFixed()).toBe("36228.50");
    const [castors, racks] = c.lines;
    expect([castors!.unitPrice.toFixed(), castors!.netAmount.toFixed()]).toEqual([
      "47.4580",
      "1898.32",
    ]);
    expect([racks!.unitPrice.toFixed(), racks!.netAmount.toFixed()]).toEqual([
      "2820.0300",
      "42300.45",
    ]);
    expect(c.netAmount.toFixed()).toBe("44198.77");
    expect(c.zuschlagAmount.toFixed()).toBe("7970.27");
    expect(c.vatAmount.toFixed()).toBe("8397.77");
    expect(c.grossAmount.toFixed()).toBe("52596.54");
  });

  it("reduced VAT 7 %", () => {
    const c = calculate([RACKS, CASTORS], "22", 7);
    expect([c.vatAmount.toFixed(), c.grossAmount.toFixed()]).toEqual(["3093.91", "47292.68"]);
  });

  it("bounds 0 and 100 %, rejects outside", () => {
    expect(calculate([CASTORS], "0", 19).netAmount.toFixed()).toBe("1556.00");
    expect(calculate([CASTORS], "100", 19).netAmount.toFixed()).toBe("3112.00");
    expect(() => calculate([CASTORS], "100.01", 19)).toThrow(RangeError);
    expect(() => calculate([CASTORS], "-0.01", 19)).toThrow(RangeError);
  });

  it("reports unpriced lines instead of guessing", () => {
    const c = calculate(
      [CASTORS, { ...CASTORS, itemId: "x", position: 30, unitCost: null }],
      "10",
      19,
    );
    expect(c.missingPricePositions).toEqual([30]);
    expect(c.lines.map((l) => l.position)).toEqual([10]);
  });

  it("contract quote: 100 x 12.50 at 25 % (integration test figures)", () => {
    const c = calculate(
      [
        {
          itemId: "i",
          position: 10,
          quantity: "100.000",
          unitCost: "12.5000",
          materialCost: "1250.00",
          laborCost: "0",
        },
      ],
      "25",
      19,
    );
    expect([c.netAmount.toFixed(), c.vatAmount.toFixed(), c.grossAmount.toFixed()]).toEqual([
      "1562.50",
      "296.88",
      "1859.38",
    ]);
  });

  it("splits custom builds into material and labor from their components", () => {
    const [line] = lineInputs([
      {
        id: "rack",
        position: 10,
        kind: "finished_good",
        quantity: "15.000",
        unit_cost: "2311.5000",
        extended_cost: "34672.50",
        components: [
          {
            id: "a",
            position: 1,
            kind: "raw_material",
            quantity: "30",
            unit_cost: "148.5",
            extended_cost: "4455.00",
            components: [],
          },
          {
            id: "b",
            position: 2,
            kind: "labor",
            quantity: "45",
            unit_cost: "92",
            extended_cost: "4140.00",
            components: [],
          },
        ],
      } as never,
    ]);
    expect([Dec.from(line!.materialCost).toFixed(2), Dec.from(line!.laborCost).toFixed(2)]).toEqual(
      ["4455.00", "4140.00"],
    );
  });
});

describe("Dec", () => {
  it("rounds half up, away from zero, like Python ROUND_HALF_UP", () => {
    expect(Dec.from("2.345").quantize(2).toFixed()).toBe("2.35");
    expect(Dec.from("-2.345").quantize(2).toFixed()).toBe("-2.35");
    expect(Dec.from("2.344999").quantize(2).toFixed()).toBe("2.34");
    expect(Dec.from("0.0005").quantize(3).toFixed()).toBe("0.001");
  });

  it("is exact where floats are not", () => {
    expect(Dec.from("0.1").add("0.2").toString()).toBe("0.3");
    expect(priceLine("0.07", "3", "15").lineTotal.toFixed()).toBe("0.24"); // 0.0805 x 3 = 0.2415
  });

  it("parses API decimal strings including exponents", () => {
    expect(Dec.from("1E+3").toFixed(3)).toBe("1000.000");
    expect(Dec.from("12.50").toString()).toBe("12.5");
    expect(() => Dec.from("1,5")).toThrow();
  });
});
