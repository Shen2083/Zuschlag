/**
 * The backend-for-frontend proxy (src/app/api/zuschlag/[...path]/route.ts):
 * path allowlist, CSRF check and server-side tenant injection.
 */
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GET, PATCH } from "@/app/api/zuschlag/[...path]/route";

const upstream = vi.fn();

beforeEach(() => {
  process.env.DEV_TENANT_ID = "5e1d0c3a-7b1f-4c2e-9a55-0d3f6c8b2a10";
  process.env.ZUSCHLAG_AUTH_MODE = "dev_headers";
  delete process.env.ZUSCHLAG_ENVIRONMENT;
  upstream
    .mockReset()
    .mockResolvedValue(
      new Response("{}", { status: 200, headers: { "content-type": "application/json" } }),
    );
  vi.stubGlobal("fetch", upstream);
});
afterEach(() => vi.unstubAllGlobals());

const ctx = (path: string) => ({ params: Promise.resolve({ path: path.split("/") }) });

function patch(headers: Record<string, string>) {
  // Inside Docker the standalone server sees its bind address, not the browser's host.
  return new NextRequest("http://0.0.0.0:3000/api/zuschlag/api/v1/quotes/q1/items/i1", {
    method: "PATCH",
    body: '{"quantity":"5"}',
    headers: { "content-type": "application/json", ...headers },
  });
}

describe("CSRF check", () => {
  it("accepts a same-origin write behind Docker (bind address differs from Host)", async () => {
    const res = await PATCH(
      patch({
        host: "localhost:3000",
        origin: "http://localhost:3000",
        "sec-fetch-site": "same-origin",
      }),
      ctx("api/v1/quotes/q1/items/i1"),
    );
    expect(res.status).toBe(200);
    const [, init] = upstream.mock.calls[0]!;
    expect(init.headers["X-Tenant-ID"]).toBe(process.env.DEV_TENANT_ID);
  });

  it.each([
    ["foreign Origin", { host: "localhost:3000", origin: "https://evil.example" }],
    ["cross-site fetch", { host: "localhost:3000", "sec-fetch-site": "cross-site" }],
    ["same-site subdomain", { host: "localhost:3000", "sec-fetch-site": "same-site" }],
  ])("refuses a %s", async (_, headers) => {
    const res = await PATCH(patch(headers), ctx("api/v1/quotes/q1/items/i1"));
    expect(res.status).toBe(403);
    expect(upstream).not.toHaveBeenCalled();
  });
});

describe("allowlist and auth", () => {
  it("does not expose SAP inbound ingestion", async () => {
    const res = await GET(
      new NextRequest("http://localhost:3000/api/zuschlag/api/v1/sap/matmas"),
      ctx("api/v1/sap/matmas"),
    );
    expect(res.status).toBe(404);
    expect(upstream).not.toHaveBeenCalled();
  });

  it("refuses dev_headers in production", async () => {
    process.env.ZUSCHLAG_ENVIRONMENT = "production";
    const res = await GET(
      new NextRequest("http://localhost:3000/api/zuschlag/api/v1/quotes"),
      ctx("api/v1/quotes"),
    );
    expect(res.status).toBe(500);
    expect(upstream).not.toHaveBeenCalled();
  });
});
