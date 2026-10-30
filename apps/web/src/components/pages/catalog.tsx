"use client";

import { useState } from "react";
import { createColumnHelper } from "@tanstack/react-table";
import type { MaterialOut } from "@zuschlag/api-types";
import { Check, Minus } from "lucide-react";

import { DataTable, SearchInput, Toolbar, type ColumnMeta } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/input";
import { useI18n } from "@/i18n";
import { useMaterials } from "@/lib/api/queries";
import { formatMoney } from "@/lib/format";
import { useDebounced } from "@/lib/use-debounced";

const col = createColumnHelper<MaterialOut>();
const TYPES = ["", "FERT", "HALB", "ROH", "HAWA", "DIEN"];

export function CatalogPage() {
  const { t, locale } = useI18n();
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const query = useDebounced(q);
  const { data, isLoading, error } = useMaterials({ q: query, type });

  const columns = [
    col.accessor("matnr", {
      header: t("catalog.matnr"),
      meta: { className: "w-44" } satisfies ColumnMeta,
      cell: (c) => <span className="font-mono font-medium">{c.getValue()}</span>,
    }),
    col.accessor("description", {
      header: t("catalog.description"),
      cell: (c) => {
        const en = (c.row.original.descriptions as Record<string, string>).EN;
        return (
          <div className="min-w-0">
            <p className="truncate">{c.getValue() ?? "—"}</p>
            {en && en !== c.getValue() && (
              <p className="truncate text-[11px] text-muted-foreground">EN: {en}</p>
            )}
          </div>
        );
      },
    }),
    col.accessor("material_type", {
      header: t("catalog.type"),
      meta: { className: "w-28" } satisfies ColumnMeta,
      cell: (c) =>
        c.getValue() ? (
          <Badge variant="outline" className="font-mono">
            {c.getValue()}
          </Badge>
        ) : (
          "—"
        ),
    }),
    col.accessor("material_group", {
      header: t("catalog.group"),
      meta: { className: "w-28" } satisfies ColumnMeta,
      cell: (c) => <span className="font-mono">{c.getValue() ?? "—"}</span>,
    }),
    col.accessor("base_uom", {
      header: t("catalog.uom"),
      meta: { className: "w-20" } satisfies ColumnMeta,
      cell: (c) => <span className="font-mono">{c.getValue()}</span>,
    }),
    col.accessor("standard_price", {
      header: t("catalog.price"),
      meta: { align: "right", className: "w-44" } satisfies ColumnMeta,
      cell: (c) => {
        const m = c.row.original;
        if (!m.standard_price) return <span className="text-warning-foreground">—</span>;
        return (
          <span>
            {formatMoney(m.standard_price, m.price_currency ?? "EUR", locale, { places: 4 })}
            <span className="ml-1 text-[11px] text-muted-foreground">
              {t("catalog.per", { unit: `${m.price_unit} ${m.base_uom}` })}
            </span>
          </span>
        );
      },
    }),
    col.accessor("has_embedding", {
      header: t("catalog.embedding"),
      meta: { className: "w-20" } satisfies ColumnMeta,
      cell: (c) =>
        c.getValue() ? (
          <Check className="size-3.5 text-success" aria-label={t("common.yes")} />
        ) : (
          <Minus className="size-3.5" aria-label={t("common.no")} />
        ),
    }),
    col.accessor("is_active", {
      header: t("catalog.active"),
      meta: { className: "w-16" } satisfies ColumnMeta,
      cell: (c) =>
        c.getValue() ? (
          <Check className="size-3.5 text-success" aria-label={t("common.yes")} />
        ) : (
          <Badge variant="destructive">{t("common.no")}</Badge>
        ),
    }),
    col.accessor("source_docnum", {
      header: t("catalog.docnum"),
      meta: { align: "right", className: "w-24" } satisfies ColumnMeta,
      cell: (c) => (
        <span className="font-mono text-[11px] text-muted-foreground">{c.getValue() ?? "—"}</span>
      ),
    }),
  ];

  return (
    <>
      <PageHeader title={t("catalog.title")} documentTitle={t("catalog.title")} />
      <Toolbar>
        <SearchInput value={q} onChange={setQ} placeholder={t("common.search")} />
        <Select
          value={type}
          onChange={(e) => setType(e.target.value)}
          aria-label={t("catalog.type")}
        >
          {TYPES.map((x) => (
            <option key={x} value={x}>
              {x || t("catalog.allTypes")}
            </option>
          ))}
        </Select>
        <span className="ml-auto text-xs text-muted-foreground">
          {data && t("common.total", { count: data.total })}
        </span>
      </Toolbar>
      <div className="min-h-0 flex-1 overflow-auto">
        <DataTable
          data={data?.items}
          columns={columns}
          label={t("catalog.title")}
          loading={isLoading}
          error={error}
          getRowId={(r) => r.id}
        />
      </div>
    </>
  );
}
