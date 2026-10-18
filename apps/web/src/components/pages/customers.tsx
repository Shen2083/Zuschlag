"use client";

import { useState } from "react";
import { createColumnHelper } from "@tanstack/react-table";
import type { CustomerOut } from "@zuschlag/api-types";

import { DataTable, SearchInput, Toolbar, type ColumnMeta } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { useI18n } from "@/i18n";
import { useCustomers } from "@/lib/api/queries";
import { useDebounced } from "@/lib/use-debounced";

const col = createColumnHelper<CustomerOut>();

export function CustomersPage() {
  const { t } = useI18n();
  const [q, setQ] = useState("");
  const query = useDebounced(q);
  const { data, isLoading, error } = useCustomers({ q: query });

  const columns = [
    col.accessor("kunnr", {
      header: t("customers.kunnr"),
      meta: { className: "w-32" } satisfies ColumnMeta,
      cell: (c) => <span className="font-mono font-medium">{c.getValue()}</span>,
    }),
    col.accessor("name1", {
      header: t("customers.name"),
      cell: (c) => (
        <span>
          {c.getValue()}
          {c.row.original.name2 && (
            <span className="text-muted-foreground"> · {c.row.original.name2}</span>
          )}
          {!c.row.original.is_active && (
            <Badge variant="destructive" className="ml-2">
              inaktiv
            </Badge>
          )}
        </span>
      ),
    }),
    col.accessor((r) => [r.postal_code, r.city].filter(Boolean).join(" "), {
      id: "city",
      header: t("customers.city"),
      meta: { className: "w-48" } satisfies ColumnMeta,
    }),
    col.accessor("country", {
      header: t("customers.country"),
      meta: { className: "w-16" } satisfies ColumnMeta,
      cell: (c) => <span className="font-mono">{c.getValue() ?? "—"}</span>,
    }),
    col.display({
      id: "areas",
      header: `${t("customers.salesAreas")} · ${t("customers.terms")}`,
      cell: (c) => (
        <span className="flex flex-wrap gap-1">
          {c.row.original.sales_areas.map((a) => (
            <Badge
              key={`${a.sales_org}-${a.distribution_channel}-${a.division}`}
              variant="outline"
              className="font-mono"
            >
              {a.sales_org}/{a.distribution_channel}/{a.division} · {a.currency ?? "—"} ·{" "}
              {a.payment_terms ?? "—"}
            </Badge>
          ))}
        </span>
      ),
    }),
  ];

  return (
    <>
      <PageHeader title={t("customers.title")} />
      <Toolbar>
        <SearchInput value={q} onChange={setQ} placeholder={t("common.search")} />
        <span className="ml-auto text-xs text-muted-foreground">
          {data && t("common.total", { count: data.total })}
        </span>
      </Toolbar>
      <div className="min-h-0 flex-1 overflow-auto">
        <DataTable
          data={data?.items}
          columns={columns}
          label={t("customers.title")}
          loading={isLoading}
          error={error}
          getRowId={(r) => r.id}
        />
      </div>
    </>
  );
}
