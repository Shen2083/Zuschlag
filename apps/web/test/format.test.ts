import { describe, expect, it } from "vitest";

import {
  decimalForInput,
  formatMoney,
  formatNumber,
  formatPercent,
  parseDecimalInput,
} from "@/lib/format";

const NBSP = " ";

describe("German locale formatting", () => {
  it("formats money as 1.250,50 €", () => {
    expect(formatMoney("1250.5", "EUR", "de")).toBe(`1.250,50${NBSP}€`);
    expect(formatMoney("52596.54", "EUR", "de")).toBe(`52.596,54${NBSP}€`);
    expect(formatMoney("1234567.891", "EUR", "de")).toBe(`1.234.567,89${NBSP}€`);
  });

  it("keeps up to four decimals for unit prices, never through a float", () => {
    expect(formatMoney("47.4580", "EUR", "de", { places: 4 })).toBe(`47,458${NBSP}€`);
    expect(formatMoney("9007199254740993.01", "EUR", "de")).toBe(
      `9.007.199.254.740.993,01${NBSP}€`,
    );
  });

  it("English for comparison", () => {
    expect(formatMoney("1250.5", "EUR", "en")).toBe("€1,250.50");
  });

  it("numbers and percent", () => {
    expect(formatNumber("1500.000", "de")).toBe("1.500");
    expect(formatNumber("37.5", "de")).toBe("37,5");
    expect(formatPercent("22.50", "de")).toBe("22,5 %");
  });

  it("parses what estimators type", () => {
    expect(parseDecimalInput("22,5", "de")).toBe("22.5");
    expect(parseDecimalInput("1.250,50", "de")).toBe("1250.5");
    expect(parseDecimalInput("22.5", "de")).toBe("22.5");
    expect(parseDecimalInput("1.250", "de")).toBe("1250");
    expect(parseDecimalInput("12 %", "de")).toBe("12");
    expect(parseDecimalInput("abc", "de")).toBeNull();
    expect(parseDecimalInput("1,250.5", "en")).toBe("1250.5");
    expect(decimalForInput("22.50", "de")).toBe("22,5");
  });
});
