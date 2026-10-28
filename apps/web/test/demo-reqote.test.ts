/** The demo's IDoc renderer produces exactly the interface contract's bytes. */
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { formatMenge, renderReqote, sha256Hex } from "@/lib/demo/reqote";

const CONTRACT = readFileSync(
  new URL("../../api/tests/fixtures/sap/quote_as_output.txt", import.meta.url),
);

const PROFILE = {
  mandt: "800",
  sender_port: "SAPERP",
  sender_partner: "CLNT800",
  receiver_port: "RECEIVER_PORT",
  receiver_partner: "EXT_SYSTEM",
  vendor_number: "0000200000",
  vendor_name: "Muster Lieferant AG",
};

describe("demo REQOTE renderer", () => {
  it("matches quote_as_output.txt byte for byte", async () => {
    const xml = renderReqote(
      {
        docnum: "0000000000987654",
        belnr: "0045001234",
        curcy: "EUR",
        zterm: "NT30",
        soldTo: {
          partn: "0000100000",
          name1: "Muster Einkäufer GmbH",
          ort01: "Musterstadt",
          pstlz: "12345",
          land1: "DE",
        },
        items: [
          {
            posex: 10,
            menge: "100.000",
            menee: "PCE",
            idnlf: "shenai",
            ktext: "Muster-Ersatzteil Premium",
          },
        ],
      },
      PROFILE,
    );
    const bytes = Buffer.from(xml, "utf-8");
    expect(bytes.equals(CONTRACT)).toBe(true);
    expect(await sha256Hex(xml)).toMatch(/^[0-9a-f]{64}$/);
  });

  it("formats quantities with three decimals, rounding half up", () => {
    expect(["100", "37.5", "0.0005", "12.3456"].map(formatMenge)).toEqual([
      "100.000",
      "37.500",
      "0.001",
      "12.346",
    ]);
  });

  it("escapes XML special characters", () => {
    const xml = renderReqote(
      {
        docnum: "1".padStart(16, "0"),
        belnr: "AN-1",
        curcy: "EUR",
        zterm: "NT30",
        soldTo: { partn: "1", name1: "Müller & Söhne <GmbH>" },
        items: [{ posex: 10, menge: "1", menee: "PCE", idnlf: "x", ktext: "a<b" }],
      },
      PROFILE,
    );
    expect(xml).toContain("<NAME1>Müller &amp; Söhne &lt;GmbH&gt;</NAME1>");
    expect(xml).toContain("<KTEXT>a&lt;b</KTEXT>");
  });
});
