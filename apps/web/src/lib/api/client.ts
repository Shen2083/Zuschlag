/**
 * Typed API client. Request and response types are generated from the API's
 * OpenAPI document (@zuschlag/api-types), so a backend schema change that the
 * UI does not follow fails `pnpm typecheck`.
 */
import createClient from "openapi-fetch";
import type { ApiErrorBody, paths } from "@zuschlag/api-types";

export const api = createClient<paths>({ baseUrl: "/api/zuschlag" });

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    /** Every reason the server listed (approval / export blockers). */
    readonly reasons: string[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function describe(status: number, body: ApiErrorBody | undefined): ApiError {
  const detail = body?.detail;
  if (typeof detail === "string") return new ApiError(status, detail);
  if (Array.isArray(detail)) {
    const text = detail.map((e) => `${e.loc.slice(1).join(".")}: ${e.msg}`).join("; ");
    return new ApiError(status, text || `HTTP ${status}`);
  }
  if (detail && typeof detail === "object")
    return new ApiError(status, detail.message, detail.reasons);
  return new ApiError(status, `HTTP ${status}`);
}

/** Unwrap an openapi-fetch result: data, or a thrown ApiError. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (error !== undefined || !response.ok) throw describe(response.status, error as ApiErrorBody);
  return data as T;
}
