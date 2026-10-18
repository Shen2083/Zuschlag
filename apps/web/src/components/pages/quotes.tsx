"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createColumnHelper } from "@tanstack/react-table";
import type { QuoteStatus, QuoteSummary } from "@zuschlag/api-types";
import { TriangleAlert } from "lucide-react";

import { DataTable, SearchInput, Toolbar, type ColumnMeta } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { QuoteStatusBadge } from "@/components/status-badge";
import { useI18n } from "@/i18n";
import { useQuotes } from "@/lib/api/queries";
import { formatDate, formatDateTime, formatMoney, formatPercent } from "@/lib/format";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";

const col = createColumnHelper<QuoteSummary>();
const STATUSES: Array<QuoteStatus | undefined> = [
  undefined,
  "needs_review",
  "draft",
  "approved",
  "synced",
];

export function QuotesPage() {
  const { t, locale } = useI18n();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<QuoteStatus | undefined>();
  const query = useDebounced(q);
  const { data, isLoading, error } = useQuotes({ q: query, status });

  const columns = [
    col.accessor("quote_number", {
      header: t("quotes.number"),
      meta: { className: "w-40" } satisfies ColumnMeta,
      cell: (c) => <span className="font-mono font-medium">{c.getValue()}</span>,
    }),
    col.accessor("status", {
      header: "Status",
      meta: { className: "w-36" } satisfies ColumnMeta,
      cell: (c) => <QuoteStatusBadge status={c.getValue()} />,
    }),
    col.accessor("customer_name", {
      header: t("quotes.customer"),
      cell: (c) => (
        <span className="flex min-w-0 items-baseline gap-2">
          <span className="truncate">{c.getValue() ?? "—"}</span>
          {c.row.original.kunnr && (
            <span className="font-mono text-[11px] text-muted-foreground">
              {c.row.original.kunnr}
            </span>
          )}
        </span>
      ),
    }),
    col.accessor("rfq_subject", {
      header: t("quotes.rfq"),
      cell: (c) => (
        <span className="block max-w-xs truncate text-muted-foreground">{c.getValue() ?? "—"}</span>
      ),
    }),
    col.accessor("items", {
      header: t("quotes.items"),
      meta: { align: "right", className: "w-16" } satisfies ColumnMeta,
    }),
    col.accessor("review_items", {
      header: t("quotes.review"),
      meta: { align: "right", className: "w-20" } satisfies ColumnMeta,
      cell: (c) =>
        c.getValue() ? (
          <span className="inline-flex items-center gap-1 text-warning-foreground">
            <TriangleAlert className="size-3" aria-hidden />
            {c.getValue()}
          </span>
        ) : (
          "—"
        ),
    }),
    col.accessor("margin_pct", {
      header: t("quotes.zuschlag"),
      meta: { align: "right", className: "w-24" } satisfies ColumnMeta,
      cell: (c) => formatPercent(c.getValue(), locale),
    }),
    col.accessor("net_total", {
      header: t("quotes.net"),
      meta: { align: "right", className: "w-32" } satisfies ColumnMeta,
      sortingFn: (a, b) => Number(a.original.net_total) - Number(b.original.net_total),
      cell: (c) => formatMoney(c.getValue(), c.row.original.currency, locale),
    }),
    col.accessor("requested_delivery_date", {
      header: t("quotes.delivery"),
      meta: { className: "w-28" } satisfies ColumnMeta,
      cell: (c) => formatDate(c.getValue(), locale),
    }),
    col.accessor("created_at", {
      header: t("quotes.created"),
      meta: { className: "w-40" } satisfies ColumnMeta,
      cell: (c) => formatDateTime(c.getValue(), locale),
    }),
  ];

  return (
    <>
      <PageHeader title={t("quotes.title")} />
      <Toolbar>
        <SearchInput value={q} onChange={setQ} placeholder={t("common.search")} />
        <div role="radiogroup" aria-label="Status" className="flex rounded-md border p-0.5">
          {STATUSES.map((s) => (
            <button
              key={s ?? "all"}
              type="button"
              role="radio"
              aria-checked={status === s}
              onClick={() => setStatus(s)}
              className={cn(
                "rounded px-2 py-0.5 text-xs",
                status === s ? "bg-foreground text-background" : "hover:bg-secondary",
              )}
            >
              {s ? t(`status.${s}`) : t("common.all")}
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs text-muted-foreground">
          {data && t("common.total", { count: data.total })}
        </span>
      </Toolbar>
      <div className="min-h-0 flex-1 overflow-auto">
        <DataTable
          data={data?.items}
          columns={columns}
          label={t("quotes.title")}
          loading={isLoading}
          error={error}
          getRowId={(r) => r.id}
          onOpen={(r) => router.push(`/quotes/${r.id}`)}
        />
      </div>
    </>
  );
}
