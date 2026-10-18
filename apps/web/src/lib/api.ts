import "server-only";

export interface ApiHealth {
  status: "ok";
  environment: string;
  cloud_provider: string;
  region: string;
  llm: { provider: string; zdr_attested: boolean };
}

const API_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

/** Server-side only: the API URL and responses never reach the browser bundle. */
export async function getApiHealth(): Promise<ApiHealth | null> {
  try {
    const res = await fetch(`${API_URL}/healthz`, {
      cache: "no-store",
      signal: AbortSignal.timeout(1500),
    });
    return res.ok ? ((await res.json()) as ApiHealth) : null;
  } catch {
    return null;
  }
}
