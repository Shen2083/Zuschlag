"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
  type ExpandedState,
  type Row,
} from "@tanstack/react-table";
import type { ItemUpdate, QuoteItemOut } from "@zuschlag/api-types";
import { ChevronRight, Loader2, Sigma, TriangleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import { useI18n, type Translate } from "@/i18n";
import { Dec } from "@/lib/decimal";
import {
  decimalForInput,
  formatMoney,
  formatNumber,
  parseDecimalInput,
  posex,
  type Locale,
} from "@/lib/format";
import { cn } from "@/lib/utils";

type Field = "matnr" | "description" | "quantity" | "uom" | "unit_cost";

interface ColumnMeta {
  field?: Field;
  align?: "right";
  className?: string;
}

const TYPE_OF: Record<QuoteItemOut["kind"], "material" | "labor" | "part"> = {
  raw_material: "material",
  semi_finished: "material",
  labor: "labor",
  service: "labor",
  purchased_part: "part",
  finished_good: "part",
};
const TYPE_STYLE = {
  material: "border-accent/30 bg-accent/10 text-accent",
  labor: "border-[oklch(0.6_0.2_300/30%)] bg-[oklch(0.6_0.2_300/10%)] text-[oklch(0.45_0.2_300)]",
  part: "border-border bg-secondary text-secondary-foreground",
} as const;

/** Green above 90 %, amber below 75 % or whenever a human must review. */
export function ConfidenceBadge({ item }: { item: QuoteItemOut }) {
  const { t, locale } = useI18n();
  if (item.match_status === "NOT_APPLICABLE")
    return <span className="text-muted-foreground">—</span>;
  if (item.match_method === "manual" && item.match_status === "MATCHED") {
    return <Badge variant="secondary">{t("studio.manual")}</Badge>;
  }
  const c = Dec.tryFrom(item.match_confidence);
  const pct = c ? c.mul(100).quantize(0) : null;
  const review = item.match_status === "NEEDS_HUMAN_REVIEW";
  const variant =
    review || (pct && pct.cmp(75) < 0) ? "warning" : pct && pct.cmp(90) > 0 ? "success" : "outline";
  const label = pct ? `${formatNumber(pct, locale)} %` : t("studio.review");
  return (
    <Badge
      variant={variant}
      aria-label={t("studio.confidence", { value: label })}
      className="tabular-nums"
    >
      {review && <TriangleAlert aria-hidden />}
      {label}
    </Badge>
  );
}

function hasKids(item: QuoteItemOut) {
  return item.components.length > 0;
}

function editable(item: QuoteItemOut, field: Field, locked: boolean): boolean {
  if (locked) return false;
  if (field === "matnr") return item.kind !== "labor";
  if (field === "unit_cost") return !hasKids(item);
  return true;
}

function rawValue(item: QuoteItemOut, field: Field, locale: Locale): string {
  switch (field) {
    case "quantity":
      return decimalForInput(item.quantity, locale);
    case "unit_cost":
      return decimalForInput(item.unit_cost, locale);
    default:
      return item[field] ?? "";
  }
}

/** Parse an edited cell into a PATCH body; `null` = nothing changed, string = error. */
function toPatch(
  item: QuoteItemOut,
  field: Field,
  input: string,
  locale: Locale,
  t: Translate,
): ItemUpdate | null | string {
  const value = input.trim();
  switch (field) {
    case "matnr":
      return value === (item.matnr ?? "") ? null : { matnr: value || null };
    case "description":
      if (!value) return t("common.error");
      return value === item.description ? null : { description: value };
    case "uom": {
      const uom = value.toUpperCase();
      if (!/^[A-Z0-9]{2,3}$/.test(uom)) return "PCE, KGM, MTR, HUR…";
      return uom === item.uom ? null : { uom };
    }
    case "quantity": {
      const qty = parseDecimalInput(value, locale);
      if (!qty || Dec.from(qty).cmp(0) <= 0) return "> 0";
      return Dec.from(qty).eq(item.quantity) ? null : { quantity: qty };
    }
    case "unit_cost": {
      if (!value) return item.unit_cost === null ? null : { unit_cost: null };
      const cost = parseDecimalInput(value, locale);
      if (!cost || Dec.from(cost).isNegative()) return "≥ 0";
      return item.unit_cost !== null && Dec.from(cost).eq(item.unit_cost)
        ? null
        : { unit_cost: cost };
    }
  }
}

const col = createColumnHelper<QuoteItemOut>();

export function BomTable({
  items,
  currency,
  locked,
  pendingItemIds,
  onEdit,
}: {
  items: QuoteItemOut[];
  currency: string;
  locked: boolean;
  pendingItemIds: Set<string>;
  onEdit: (itemId: string, patch: ItemUpdate) => void;
}) {
  const { t, locale } = useI18n();
  const [expanded, setExpanded] = useState<ExpandedState>(() =>
    Object.fromEntries(
      items
        .filter((i) =>
          i.components.some((k) => k.match_status === "NEEDS_HUMAN_REVIEW" || k.catalog_warning),
        )
        .map((i) => [i.id, true]),
    ),
  );
  const [active, setActive] = useState<{ row: number; col: number }>({ row: 0, col: 1 });
  const [editing, setEditing] = useState<{
    rowId: string;
    field: Field;
    value: string;
    error?: string;
  } | null>(null);
  const gridRef = useRef<HTMLTableElement>(null);
  const money = (v: string | null | undefined, places = 2) =>
    formatMoney(v, currency, locale, { places, minPlaces: 2 });

  const columns = useMemo(
    () => [
      col.display({
        id: "pos",
        header: t("studio.columns.pos"),
        meta: { className: "w-[76px]" } satisfies ColumnMeta,
        cell: ({ row }) => (
          <div className="flex items-center gap-1" style={{ paddingLeft: row.depth * 14 }}>
            {row.getCanExpand() ? (
              <button
                type="button"
                tabIndex={-1}
                onClick={row.getToggleExpandedHandler()}
                aria-expanded={row.getIsExpanded()}
                aria-label={row.getIsExpanded() ? t("studio.collapse") : t("studio.expand")}
                className="rounded p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
              >
                <ChevronRight
                  className={cn(
                    "size-3.5 transition-transform",
                    row.getIsExpanded() && "rotate-90",
                  )}
                  aria-hidden
                />
              </button>
            ) : (
              <span className="w-[18px]" />
            )}
            <span className="font-mono tabular-nums">
              {row.depth === 0
                ? posex(row.original.position)
                : `${row.getParentRow()?.original.position}.${row.original.position}`}
            </span>
            {pendingItemIds.has(row.original.id) && (
              <Loader2
                className="size-3 animate-spin text-muted-foreground"
                aria-label={t("studio.saving")}
              />
            )}
          </div>
        ),
      }),
      col.accessor("matnr", {
        header: t("studio.columns.matnr"),
        meta: { field: "matnr", className: "w-[128px]" } satisfies ColumnMeta,
        cell: ({ row }) => {
          const i = row.original;
          const warning = i.catalog_warning;
          return (
            <div className="flex items-center gap-1.5">
              <span className={cn("truncate font-mono", !i.matnr && "text-muted-foreground")}>
                {i.matnr ?? "—"}
              </span>
              {warning && (
                <Tooltip content={t(`studio.warning.${warning}`)}>
                  <span
                    role="img"
                    tabIndex={-1}
                    aria-label={t(`studio.warning.${warning}`)}
                    className={cn(
                      "shrink-0",
                      warning === "needs_fert" ? "text-accent" : "text-warning-foreground",
                    )}
                  >
                    <TriangleAlert className="size-3.5" aria-hidden />
                  </span>
                </Tooltip>
              )}
            </div>
          );
        },
      }),
      col.accessor("description", {
        header: t("studio.columns.maktx"),
        meta: { field: "description" } satisfies ColumnMeta,
        cell: ({ row }) => {
          const i = row.original;
          const specs = i.specs
            .map((s) => `${s.name}: ${s.value}${s.unit ? ` ${s.unit}` : ""}`)
            .join(" · ");
          return (
            <div className="min-w-0">
              <p className="truncate" title={i.requested_description ?? i.description}>
                {i.description}
              </p>
              {specs && <p className="truncate text-[11px] text-muted-foreground">{specs}</p>}
            </div>
          );
        },
      }),
      col.accessor("kind", {
        header: t("studio.columns.type"),
        meta: { className: "w-[72px]" } satisfies ColumnMeta,
        cell: ({ row }) => {
          const type = TYPE_OF[row.original.kind];
          return (
            <Badge
              variant="outline"
              className={TYPE_STYLE[type]}
              title={`${row.original.kind}${row.original.material_type ? ` · MTART ${row.original.material_type}` : ""}`}
            >
              {t(`studio.type.${type}`)}
            </Badge>
          );
        },
      }),
      col.accessor("quantity", {
        header: t("studio.columns.qty"),
        meta: { field: "quantity", align: "right", className: "w-[64px]" } satisfies ColumnMeta,
        cell: ({ getValue }) => (
          <span className="tabular-nums">{formatNumber(getValue(), locale)}</span>
        ),
      }),
      col.accessor("uom", {
        header: t("studio.columns.unit"),
        meta: { field: "uom", className: "w-[44px]" } satisfies ColumnMeta,
        cell: ({ getValue }) => <span className="font-mono">{getValue()}</span>,
      }),
      col.accessor("unit_cost", {
        header: t("studio.columns.cost"),
        meta: { field: "unit_cost", align: "right", className: "w-[96px]" } satisfies ColumnMeta,
        cell: ({ row }) => (
          <span className="inline-flex items-center gap-1 tabular-nums">
            {hasKids(row.original) && (
              <Tooltip content={t("studio.rolledUp")}>
                <Sigma className="size-3 text-muted-foreground" aria-label={t("studio.rolledUp")} />
              </Tooltip>
            )}
            {money(row.original.unit_cost, 4)}
          </span>
        ),
      }),
      col.display({
        id: "confidence",
        header: t("studio.columns.confidence"),
        meta: { className: "w-[66px]" } satisfies ColumnMeta,
        cell: ({ row }) => <ConfidenceBadge item={row.original} />,
      }),
      col.accessor("unit_price", {
        header: t("studio.columns.price"),
        meta: { align: "right", className: "w-[96px]" } satisfies ColumnMeta,
        cell: ({ row }) =>
          row.depth ? null : (
            <span className="tabular-nums">{money(row.original.unit_price, 4)}</span>
          ),
      }),
      col.accessor("line_total", {
        header: t("studio.columns.total"),
        meta: { align: "right", className: "w-[100px]" } satisfies ColumnMeta,
        cell: ({ row }) =>
          row.depth ? null : (
            <span className="font-medium tabular-nums">{money(row.original.line_total)}</span>
          ),
      }),
    ],
    [t, locale, currency, pendingItemIds], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const table = useReactTable({
    data: items,
    columns,
    state: { expanded },
    onExpandedChange: setExpanded,
    getSubRows: (row) => row.components,
    getRowId: (row) => row.id,
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
  });
  const rows = table.getRowModel().rows;
  const leafColumns = table.getVisibleLeafColumns();
  const metaOf = (index: number) => (leafColumns[index]?.columnDef.meta ?? {}) as ColumnMeta;

  // Keep the active cell inside the grid when rows collapse or the quote reloads.
  const row = Math.min(active.row, Math.max(rows.length - 1, 0));
  useEffect(() => {
    if (editing) return;
    const cell = gridRef.current?.querySelector<HTMLElement>(`[data-cell="${row}:${active.col}"]`);
    if (
      cell &&
      gridRef.current?.contains(document.activeElement) &&
      document.activeElement !== cell
    )
      cell.focus();
  }, [row, active.col, editing]);

  const startEdit = (r: Row<QuoteItemOut>, colIndex: number, initial?: string) => {
    const field = metaOf(colIndex).field;
    if (!field || !editable(r.original, field, locked)) return;
    setEditing({ rowId: r.id, field, value: initial ?? rawValue(r.original, field, locale) });
  };

  const commit = (move: "down" | "right" | "none") => {
    if (!editing) return;
    const target = rows.find((r) => r.id === editing.rowId);
    if (!target) return setEditing(null);
    const patch = toPatch(target.original, editing.field, editing.value, locale, t);
    if (typeof patch === "string") return setEditing({ ...editing, error: patch });
    if (patch) onEdit(target.original.id, patch);
    setEditing(null);
    if (move === "down") setActive((a) => ({ ...a, row: Math.min(a.row + 1, rows.length - 1) }));
    if (move === "right")
      setActive((a) => ({ ...a, col: Math.min(a.col + 1, leafColumns.length - 1) }));
    requestAnimationFrame(() =>
      gridRef.current?.querySelector<HTMLElement>("[data-cell][tabindex='0']")?.focus(),
    );
  };

  const onGridKey = (e: React.KeyboardEvent) => {
    if (editing) return;
    const r = rows[row];
    const move = (dr: number, dc: number) => {
      e.preventDefault();
      setActive({
        row: Math.max(0, Math.min(rows.length - 1, row + dr)),
        col: Math.max(0, Math.min(leafColumns.length - 1, active.col + dc)),
      });
    };
    switch (e.key) {
      case "ArrowDown":
        return move(1, 0);
      case "ArrowUp":
        return move(-1, 0);
      case "ArrowRight":
        return move(0, 1);
      case "ArrowLeft":
        return move(0, -1);
      case "Home":
        return move(0, -leafColumns.length);
      case "End":
        return move(0, leafColumns.length);
      case "Enter":
      case "F2":
        if (r) {
          e.preventDefault();
          startEdit(r, active.col);
        }
        return;
      case " ":
        if (r?.getCanExpand()) {
          e.preventDefault();
          r.toggleExpanded();
        }
        return;
      default:
        // Typing a character starts editing with that character, like a spreadsheet.
        if (
          r &&
          e.key.length === 1 &&
          !e.ctrlKey &&
          !e.metaKey &&
          !e.altKey &&
          metaOf(active.col).field
        ) {
          const field = metaOf(active.col).field!;
          if (editable(r.original, field, locked)) {
            e.preventDefault();
            startEdit(r, active.col, e.key);
          }
        }
    }
  };

  return (
    <table
      ref={gridRef}
      role="treegrid"
      aria-label={t("studio.bomPanel")}
      aria-rowcount={rows.length + 1}
      aria-describedby="bom-hint"
      onKeyDown={onGridKey}
      className="w-full min-w-[880px] table-fixed border-separate border-spacing-0 text-[12.5px]"
    >
      <caption id="bom-hint" className="sr-only">
        {t("studio.editHint")}
      </caption>
      <thead className="sticky top-0 z-10 bg-secondary">
        {table.getHeaderGroups().map((group) => (
          <tr key={group.id} role="row">
            {group.headers.map((header, i) => (
              <th
                key={header.id}
                role="columnheader"
                aria-colindex={i + 1}
                className={cn(
                  "truncate border-b px-2 py-1.5 text-left text-[11px] font-semibold tracking-wide whitespace-nowrap text-muted-foreground uppercase",
                  metaOf(i).align === "right" && "text-right",
                  metaOf(i).className,
                )}
              >
                {flexRender(header.column.columnDef.header, header.getContext())}
              </th>
            ))}
          </tr>
        ))}
      </thead>
      <tbody>
        {rows.map((r, ri) => {
          const review = r.original.match_status === "NEEDS_HUMAN_REVIEW";
          return (
            <tr
              key={r.id}
              role="row"
              aria-rowindex={ri + 2}
              aria-level={r.depth + 1}
              aria-expanded={r.getCanExpand() ? r.getIsExpanded() : undefined}
              className={cn(
                "group",
                r.depth > 0 && "bg-muted/40 text-[12px]",
                review && "bg-warning/[0.07]",
                pendingItemIds.has(r.original.id) && "opacity-70",
              )}
            >
              {r.getVisibleCells().map((cell, ci) => {
                const meta = metaOf(ci);
                const isActive = ri === row && ci === active.col;
                const isEditing =
                  editing?.rowId === r.id &&
                  editing.field === meta.field &&
                  meta.field !== undefined;
                const canEdit =
                  meta.field !== undefined && editable(r.original, meta.field, locked);
                return (
                  <td
                    key={cell.id}
                    role="gridcell"
                    data-cell={`${ri}:${ci}`}
                    tabIndex={isActive && !isEditing ? 0 : -1}
                    aria-readonly={!canEdit || undefined}
                    aria-colindex={ci + 1}
                    onClick={() => setActive({ row: ri, col: ci })}
                    onDoubleClick={() => startEdit(r, ci)}
                    className={cn(
                      "h-8 border-b px-2 align-middle outline-none",
                      ci === 0 && review && "border-l-2 border-l-warning",
                      meta.align === "right" && "text-right",
                      canEdit && "cursor-text group-hover:bg-card",
                      isActive && "ring-2 ring-ring ring-inset",
                      isEditing && "p-0",
                    )}
                  >
                    {isEditing && editing ? (
                      <CellEditor
                        value={editing.value}
                        error={editing.error}
                        align={meta.align}
                        label={`${t(`studio.columns.${columnKey(meta.field!)}`)} ${posex(r.original.position)}`}
                        onChange={(value) => setEditing({ ...editing, value, error: undefined })}
                        onCommit={commit}
                        onCancel={() => {
                          setEditing(null);
                          requestAnimationFrame(() =>
                            gridRef.current
                              ?.querySelector<HTMLElement>("[data-cell][tabindex='0']")
                              ?.focus(),
                          );
                        }}
                      />
                    ) : (
                      flexRender(cell.column.columnDef.cell, cell.getContext())
                    )}
                  </td>
                );
              })}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function columnKey(field: Field) {
  return (
    {
      matnr: "matnr",
      description: "maktx",
      quantity: "qty",
      uom: "unit",
      unit_cost: "cost",
    } as const
  )[field];
}

function CellEditor({
  value,
  error,
  align,
  label,
  onChange,
  onCommit,
  onCancel,
}: {
  value: string;
  error?: string;
  align?: "right";
  label: string;
  onChange: (value: string) => void;
  onCommit: (move: "down" | "right" | "none") => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const input = ref.current;
    if (!input) return;
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }, []);
  return (
    <input
      ref={ref}
      value={value}
      aria-label={label}
      aria-invalid={error ? true : undefined}
      title={error}
      onChange={(e) => onChange(e.target.value)}
      onBlur={() => onCommit("none")}
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === "Enter") {
          e.preventDefault();
          onCommit("down");
        } else if (e.key === "Tab") {
          e.preventDefault();
          onCommit("right");
        } else if (e.key === "Escape") {
          e.preventDefault();
          onCancel();
        }
      }}
      className={cn(
        "h-8 w-full bg-card px-2 font-[inherit] text-[12.5px] outline-2 -outline-offset-2 outline-ring",
        align === "right" && "text-right tabular-nums",
        error && "outline-destructive",
      )}
    />
  );
}
