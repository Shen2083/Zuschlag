import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { validateOrders05Quotation } from "../dist/index.js";

const example = JSON.parse(
  await readFile(new URL("../examples/orders05-quotation.example.json", import.meta.url), "utf8"),
);

test("example IDoc is valid", () => {
  const result = validateOrders05Quotation(example);
  assert.equal(result.ok, true, JSON.stringify(result.errors));
});

test("missing sold-to partner (AG) is rejected", () => {
  const bad = structuredClone(example);
  bad.E1EDKA1 = [{ PARVW: "WE", PARTN: "300184" }];
  assert.equal(validateOrders05Quotation(bad).ok, false);
});

test("comma decimal quantity is rejected", () => {
  const bad = structuredClone(example);
  bad.E1EDP01[0].MENGE = "60,5";
  assert.equal(validateOrders05Quotation(bad).ok, false);
});
