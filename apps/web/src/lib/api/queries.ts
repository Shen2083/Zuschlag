"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  IdocPreview,
  ItemUpdate,
  QuoteDetail,
  QuoteStatus,
  SapStatus,
} from "@zuschlag/api-types";

import { api, unwrap } from "@/lib/api/client";
import { applyItemPatch } from "@/lib/quote-math";

export const keys = {
  quote: (id: string) => ["quote", id] as const,
  quotes: (params: object) => ["quotes", params] as const,
  rfqs: ["rfqs"] as const,
  materials: (params: object) => ["materials", params] as const,
  customers: (params: object) => ["customers", params] as const,
  audit: ["audit"] as const,
  tenant: ["tenant"] as const,
  sapStatus: ["sap-status"] as const,
};

// ---------------------------------------------------------------- reads

export function useQuote(id: string) {
  return useQuery({
    queryKey: keys.quote(id),
    queryFn: () =>
      unwrap(api.GET("/api/v1/quotes/{quote_id}", { params: { path: { quote_id: id } } })),
  });
}

export function useQuotes(params: { status?: QuoteStatus; q?: string; offset?: number }) {
  return useQuery({
    queryKey: keys.quotes(params),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/quotes", {
          params: { query: { ...params, q: params.q || undefined, limit: 50 } },
        }),
      ),
    placeholderData: (prev) => prev,
  });
}

export function useRfqs() {
  return useQuery({
    queryKey: keys.rfqs,
    queryFn: () => unwrap(api.GET("/api/v1/rfqs", { params: { query: { limit: 200 } } })),
  });
}

export function useMaterials(params: { q?: string; type?: string; offset?: number }) {
  return useQuery({
    queryKey: keys.materials(params),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/materials", {
          params: {
            query: {
              q: params.q || undefined,
              type: params.type || undefined,
              offset: params.offset,
              limit: 100,
            },
          },
        }),
      ),
    placeholderData: (prev) => prev,
  });
}

export function useCustomers(params: { q?: string; offset?: number }) {
  return useQuery({
    queryKey: keys.customers(params),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/customers", {
          params: { query: { q: params.q || undefined, offset: params.offset, limit: 100 } },
        }),
      ),
    placeholderData: (prev) => prev,
  });
}

export function useAuditLogs() {
  return useQuery({
    queryKey: keys.audit,
    queryFn: () => unwrap(api.GET("/api/v1/audit-logs", { params: { query: { limit: 500 } } })),
  });
}

export function useAuditVerify() {
  return useMutation({ mutationFn: () => unwrap(api.GET("/api/v1/audit-logs/verify")) });
}

export function useTenant() {
  return useQuery({ queryKey: keys.tenant, queryFn: () => unwrap(api.GET("/api/v1/tenant")) });
}

/** SAP link status, polled; `apiLatencyMs` is the browser -> API round trip. */
export function useSapStatus() {
  return useQuery({
    queryKey: keys.sapStatus,
    queryFn: async (): Promise<SapStatus & { apiLatencyMs: number }> => {
      const start = performance.now();
      const status = await unwrap(api.GET("/api/v1/sap/status"));
      return { ...status, apiLatencyMs: Math.round(performance.now() - start) };
    },
    refetchInterval: 30_000,
    retry: false,
  });
}

// ---------------------------------------------------------------- writes

/** Inline BOM edit with an optimistic update and rollback on error. */
export function useUpdateItem(quoteId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["update-item", quoteId],
    mutationFn: ({ itemId, patch }: { itemId: string; patch: ItemUpdate }) =>
      unwrap(
        api.PATCH("/api/v1/quotes/{quote_id}/items/{item_id}", {
          params: { path: { quote_id: quoteId, item_id: itemId } },
          body: patch,
        }),
      ),
    onMutate: async ({ itemId, patch }) => {
      await qc.cancelQueries({ queryKey: keys.quote(quoteId) });
      const previous = qc.getQueryData<QuoteDetail>(keys.quote(quoteId));
      if (previous) qc.setQueryData(keys.quote(quoteId), applyItemPatch(previous, itemId, patch));
      return { previous };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData(keys.quote(quoteId), ctx.previous);
    },
    onSuccess: (detail) => qc.setQueryData(keys.quote(quoteId), detail),
    onSettled: () => qc.invalidateQueries({ queryKey: ["quotes"] }),
  });
}

export interface CalculateVars {
  zuschlag_pct: string;
  vat_rate: 19 | 7;
  payment_terms?: string;
  allow_terms_deviation?: boolean;
}

export function useCalculate(quoteId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["calculate", quoteId],
    mutationFn: (body: CalculateVars) =>
      unwrap(
        api.POST("/api/v1/quotes/{quote_id}/calculate", {
          params: { path: { quote_id: quoteId } },
          body,
        }),
      ),
    // The studio already shows the locally computed totals; reload the authoritative quote.
    onSettled: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: keys.quote(quoteId) }),
        qc.invalidateQueries({ queryKey: ["quotes"] }),
      ]),
  });
}

export function useApprove(quoteId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (comment?: string) =>
      unwrap(
        api.POST("/api/v1/quotes/{quote_id}/approve", {
          params: { path: { quote_id: quoteId } },
          body: comment ? { comment } : undefined,
        }),
      ),
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: keys.quote(quoteId) });
      const previous = qc.getQueryData<QuoteDetail>(keys.quote(quoteId));
      if (previous)
        qc.setQueryData(keys.quote(quoteId), { ...previous, status: "approved" as const });
      return { previous };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.previous) qc.setQueryData(keys.quote(quoteId), ctx.previous);
    },
    onSuccess: (detail) => qc.setQueryData(keys.quote(quoteId), detail),
    onSettled: () => qc.invalidateQueries({ queryKey: ["quotes"] }),
  });
}

export function useReparse(quoteId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/quotes/{quote_id}/reparse", { params: { path: { quote_id: quoteId } } }),
      ),
    onSuccess: (detail) => {
      qc.setQueryData(keys.quote(detail.id), detail);
      void qc.invalidateQueries({ queryKey: keys.quote(quoteId) });
      void qc.invalidateQueries({ queryKey: ["quotes"] });
      void qc.invalidateQueries({ queryKey: keys.rfqs });
    },
  });
}

export function useGenerateQuote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { raw_text: string; customer_id?: string }) =>
      unwrap(api.POST("/api/v1/quotes/generate-from-rfq", { body })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.rfqs });
      void qc.invalidateQueries({ queryKey: ["quotes"] });
    },
  });
}

export function usePrepareIdoc(quoteId: string) {
  return useMutation({
    mutationFn: (): Promise<IdocPreview> =>
      unwrap(
        api.POST("/api/v1/quotes/{quote_id}/sap-idoc/prepare", {
          params: { path: { quote_id: quoteId } },
        }),
      ),
  });
}

export function useSendIdoc(quoteId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { docnum: string; sha256: string }) =>
      unwrap(
        api.POST("/api/v1/quotes/{quote_id}/sap-idoc/send", {
          params: { path: { quote_id: quoteId } },
          body,
        }),
      ),
    onSuccess: (result) => {
      qc.setQueryData(keys.quote(quoteId), result.quote);
      void qc.invalidateQueries({ queryKey: ["quotes"] });
      void qc.invalidateQueries({ queryKey: keys.sapStatus });
    },
  });
}

export function useSaveSapProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (
      body: NonNullable<import("@zuschlag/api-types").TenantSettings["sap_outbound_profile"]>,
    ) => unwrap(api.PUT("/api/v1/tenant/sap-outbound-profile", { body })),
    onSuccess: (settings) => {
      qc.setQueryData(keys.tenant, settings);
      void qc.invalidateQueries({ queryKey: keys.sapStatus });
    },
  });
}
