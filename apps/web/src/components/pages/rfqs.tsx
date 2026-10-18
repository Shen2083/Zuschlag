"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createColumnHelper } from "@tanstack/react-table";
import type { RfqInboxItem } from "@zuschlag/api-types";
import { Loader2, Sparkles } from "lucide-react";

import { DataTable, type ColumnMeta } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { QuoteStatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/i18n";
import { useGenerateQuote, useRfqs } from "@/lib/api/queries";
import { formatDateTime, formatMoney } from "@/lib/format";

const col = createColumnHelper<RfqInboxItem>();

export function RfqsPage() {
  const { t, locale } = useI18n();
  const router = useRouter();
  const { data, isLoading, error } = useRfqs();

  const columns = [
    col.accessor("received_at", {
      header: t("rfqs.received"),
      meta: { className: "w-40" } satisfies ColumnMeta,
      cell: (c) => <span className="tabular-nums">{formatDateTime(c.getValue(), locale)}</span>,
    }),
    col.accessor("subject", {
      header: t("rfqs.subject"),
      cell: (c) => (
        <div className="max-w-xl min-w-0">
          <p className="truncate font-medium">{c.getValue()}</p>
          {c.row.original.preview && (
            <p className="truncate text-[11px] text-muted-foreground">{c.row.original.preview}</p>
          )}
        </div>
      ),
    }),
    col.accessor("source", {
      header: t("rfqs.source"),
      meta: { className: "w-24" } satisfies ColumnMeta,
      cell: (c) => t(`rfqs.sources.${c.getValue()}`),
    }),
    col.accessor("customer_ref", {
      header: t("rfqs.customerRef"),
      meta: { className: "w-36" } satisfies ColumnMeta,
      cell: (c) => <span className="font-mono">{c.getValue() ?? "—"}</span>,
    }),
    col.accessor((r) => r.quote?.quote_number ?? "", {
      id: "quote",
      header: t("rfqs.quote"),
      meta: { className: "w-72" } satisfies ColumnMeta,
      cell: (c) => {
        const q = c.row.original.quote;
        return q ? (
          <span className="flex items-center gap-2">
            <span className="font-mono">{q.quote_number}</span>
            <QuoteStatusBadge status={q.status} />
            <span className="ml-auto tabular-nums">
              {formatMoney(q.net_total, q.currency, locale)}
            </span>
          </span>
        ) : (
          <span className="text-muted-foreground">{t("rfqs.noQuote")}</span>
        );
      },
    }),
  ];

  return (
    <>
      <PageHeader title={t("rfqs.title")} />
      <div className="grid min-h-0 flex-1 xl:grid-cols-[1fr_380px]">
        <div className="min-h-0 overflow-auto">
          <DataTable
            data={data}
            columns={columns}
            label={t("rfqs.title")}
            loading={isLoading}
            error={error}
            getRowId={(r) => r.id}
            onOpen={(r) => r.quote && router.push(`/quotes/${r.quote.id}`)}
          />
        </div>
        <NewRfq />
      </div>
    </>
  );
}

function NewRfq() {
  const { t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const generate = useGenerateQuote();
  const [text, setText] = useState("");
  const [customer, setCustomer] = useState("");

  return (
    <form
      aria-labelledby="new-rfq"
      className="flex flex-col gap-2 border-t bg-card p-4 xl:border-t-0 xl:border-l"
      onSubmit={(e) => {
        e.preventDefault();
        generate.mutate(
          { raw_text: text, customer_id: customer.trim() || undefined },
          {
            onSuccess: (quote) => router.push(`/quotes/${quote.id}`),
            onError: (err) =>
              toast({ kind: "error", title: t("common.error"), detail: err.message }),
          },
        );
      }}
    >
      <h2
        id="new-rfq"
        className="text-xs font-semibold tracking-wide text-muted-foreground uppercase"
      >
        {t("rfqs.newTitle")}
      </h2>
      <p className="text-xs text-muted-foreground">{t("rfqs.newHelp")}</p>
      <label className="mt-1 text-xs font-medium" htmlFor="rfq-body">
        {t("rfqs.body")}
      </label>
      <Textarea
        id="rfq-body"
        required
        rows={12}
        value={text}
        onChange={(e) => setText(e.target.value)}
        className="font-mono text-xs"
      />
      <label className="text-xs font-medium" htmlFor="rfq-customer">
        {t("rfqs.customer")}
      </label>
      <Input
        id="rfq-customer"
        value={customer}
        onChange={(e) => setCustomer(e.target.value)}
        className="font-mono"
        maxLength={64}
      />
      <Button type="submit" className="mt-2" disabled={!text.trim() || generate.isPending}>
        {generate.isPending ? (
          <Loader2 className="animate-spin" aria-hidden />
        ) : (
          <Sparkles aria-hidden />
        )}
        {generate.isPending ? t("rfqs.generating") : t("rfqs.generate")}
      </Button>
    </form>
  );
}
