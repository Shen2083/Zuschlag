/**
 * Backend-for-frontend proxy: the browser talks only to this origin
 * (CSP `connect-src 'self'`), and the API URL and tenant credentials stay on
 * the server.
 *
 * Authentication mirrors the API's AUTH_MODE. In `dev_headers` mode the tenant
 * and actor come from DEV_TENANT_ID / DEV_ACTOR_ID on the server; this mode is
 * refused when ZUSCHLAG_ENVIRONMENT=production. OIDC is not implemented yet,
 * exactly as in the API.
 */
import { type NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

// Only the UI's endpoints. SAP inbound IDoc ingestion (MATMAS/DEBMAS) is system-to-system.
const ALLOWED: Array<[RegExp, ReadonlySet<string>]> = [
  [
    /^api\/v1\/quotes(\/[\w-]+(\/(items\/[\w-]+|calculate|approve|reparse|sap-idoc\/(prepare|send)))?)?$/,
    new Set(["GET", "POST", "PATCH"]),
  ],
  [/^api\/v1\/quotes\/generate-from-rfq$/, new Set(["POST"])],
  [/^api\/v1\/rfqs$/, new Set(["GET"])],
  [
    /^api\/v1\/(materials|customers|sap\/status|audit-logs|audit-logs\/verify|tenant)$/,
    new Set(["GET"]),
  ],
  [/^api\/v1\/tenant\/sap-outbound-profile$/, new Set(["PUT"])],
];
const FORWARD_RESPONSE_HEADERS = [
  "content-type",
  "x-idoc-docnum",
  "x-content-sha256",
  "content-disposition",
];

function problem(status: number, detail: string) {
  return NextResponse.json({ detail }, { status });
}

function authHeaders(): Record<string, string> | NextResponse {
  const mode = process.env.ZUSCHLAG_AUTH_MODE ?? "dev_headers";
  if (mode !== "dev_headers") return problem(501, "OIDC authentication not configured");
  if (process.env.ZUSCHLAG_ENVIRONMENT === "production") {
    return problem(500, "dev_headers authentication is not allowed in production");
  }
  const tenant = process.env.DEV_TENANT_ID;
  if (!tenant) return problem(503, "DEV_TENANT_ID is not set for the web server");
  return { "X-Tenant-ID": tenant, "X-Actor-ID": process.env.DEV_ACTOR_ID ?? "dev-user" };
}

async function proxy(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const path = (await ctx.params).path.join("/");
  const method = request.method.toUpperCase();
  const rule = ALLOWED.find(([pattern]) => pattern.test(path));
  if (!rule) return problem(404, "not found");
  if (!rule[1].has(method)) return problem(405, "method not allowed");

  // CSRF: state-changing calls must come from this origin.
  if (method !== "GET") {
    const site = request.headers.get("sec-fetch-site");
    const origin = request.headers.get("origin");
    if (
      (site && site !== "same-origin") ||
      (origin && new URL(origin).host !== request.nextUrl.host)
    ) {
      return problem(403, "cross-site request refused");
    }
  }

  const auth = authHeaders();
  if (auth instanceof NextResponse) return auth;

  const headers: Record<string, string> = {
    ...auth,
    Accept: request.headers.get("accept") ?? "application/json",
  };
  const contentType = request.headers.get("content-type");
  if (contentType) headers["Content-Type"] = contentType;

  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/${path}${request.nextUrl.search}`, {
      method,
      headers,
      body: method === "GET" ? undefined : await request.text(),
      cache: "no-store",
      // LLM extraction (generate / re-parse) can take a while.
      signal: AbortSignal.timeout(
        path.endsWith("reparse") || path.endsWith("generate-from-rfq") ? 180_000 : 30_000,
      ),
    });
  } catch {
    return problem(502, "Zuschlag API unreachable");
  }

  const out = new Headers({ "Cache-Control": "no-store" });
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  return new NextResponse(upstream.body, { status: upstream.status, headers: out });
}

export { proxy as GET, proxy as PATCH, proxy as POST, proxy as PUT };
