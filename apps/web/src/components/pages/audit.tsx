"use client";

import { createColumnHelper } from "@tanstack/react-table";
import type { AuditLogOut } from "@zuschlag/api-types";
import { Loader2, ShieldAlert, ShieldCheck } from "lucide-react";

import { DataTable, Toolbar, type ColumnMeta } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n";
import { useAuditLogs, useAuditVerify } from "@/lib/api/queries";

const col = createColumnHelper<AuditLogOut>();

export function AuditPage() {
  const { t } = useI18n();
  const { data, isLoading, error } = useAuditLogs();
  const verify = useAuditVerify();

  const columns = [
    col.accessor("seq", {
      header: t("audit.seq"),
      meta: { align: "right", className: "w-16" } satisfies ColumnMeta,
    }),
    col.accessor("timestamp_utc", {
      header: t("audit.time"),
      meta: { className: "w-48" } satisfies ColumnMeta,
      cell: (c) => (
        <span className="font-mono text-[11px]">{c.getValue().replace("T", " ").slice(0, 23)}</span>
      ),
    }),
    col.accessor("actor_id", {
      header: t("audit.actor"),
      meta: { className: "w-40" } satisfies ColumnMeta,
    }),
    col.accessor("action", {
      header: t("audit.action"),
      meta: { className: "w-56" } satisfies ColumnMeta,
      cell: (c) => <span className="font-mono">{c.getValue()}</span>,
    }),
    col.accessor((r) => `${r.entity_type}:${r.entity_id}`, {
      id: "entity",
      header: t("audit.entity"),
      cell: (c) => (
        <span
          className="block max-w-xs truncate font-mono text-[11px]"
          title={JSON.stringify(c.row.original.context)}
        >
          {c.getValue()}
        </span>
      ),
    }),
    col.accessor("entry_hash", {
      header: t("audit.hash"),
      meta: { className: "w-32" } satisfies ColumnMeta,
      cell: (c) => (
        <span className="font-mono text-[11px] text-muted-foreground" title={c.getValue()}>
          {c.getValue().slice(0, 12)}…
        </span>
      ),
    }),
  ];

  return (
    <>
      <PageHeader title={t("audit.title")} documentTitle={t("audit.title")} />
      <Toolbar>
        <p className="text-xs text-muted-foreground">{t("audit.help")}</p>
        <div className="ml-auto flex items-center gap-2" role="status" aria-live="polite">
          {verify.data &&
            (verify.data.intact ? (
              <span className="flex items-center gap-1 text-xs text-success">
                <ShieldCheck className="size-4" aria-hidden />
                {t("audit.intact")}
              </span>
            ) : (
              <span className="flex items-center gap-1 text-xs text-destructive">
                <ShieldAlert className="size-4" aria-hidden />
                {t("audit.broken", {
                  seqs: (verify.data.breaks as Array<{ seq: number }>).map((b) => b.seq).join(", "),
                })}
              </span>
            ))}
          <Button
            size="sm"
            variant="outline"
            onClick={() => verify.mutate()}
            disabled={verify.isPending}
          >
            {verify.isPending ? (
              <Loader2 className="animate-spin" aria-hidden />
            ) : (
              <ShieldCheck aria-hidden />
            )}
            {t("audit.verify")}
          </Button>
        </div>
      </Toolbar>
      <div className="min-h-0 flex-1 overflow-auto">
        <DataTable
          data={data}
          columns={columns}
          label={t("audit.title")}
          loading={isLoading}
          error={error}
          getRowId={(r) => String(r.seq)}
        />
      </div>
    </>
  );
}
