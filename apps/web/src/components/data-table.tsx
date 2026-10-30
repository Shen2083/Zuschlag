"use client";

import { useRef, useState } from "react";
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, Loader2 } from "lucide-react";

import { useServerText } from "@/lib/server-messages";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";

export interface ColumnMeta {
  align?: "right";
  className?: string;
}

/**
 * Dense, sortable list. Rows are a roving-tabindex listbox-like grid:
 * ↑/↓ move, Home/End jump, Enter opens the row.
 */
export function DataTable<T>({
  data,
  columns,
  label,
  loading,
  error,
  getRowId,
  onOpen,
  rowClassName,
}: {
  data: T[] | undefined;
  // TanStack's accessor columns are invariant in their value type; `any` is its documented idiom.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  columns: ColumnDef<T, any>[];
  label: string;
  loading?: boolean;
  error?: Error | null;
  getRowId: (row: T) => string;
  onOpen?: (row: T) => void;
  rowClassName?: (row: T) => string | undefined;
}) {
  const { t } = useI18n();
  const tr = useServerText();
  const [sorting, setSorting] = useState<SortingState>([]);
  const [active, setActive] = useState(0);
  const bodyRef = useRef<HTMLTableSectionElement>(null);
  const table = useReactTable({
    data: data ?? [],
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getRowId,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });
  const rows = table.getRowModel().rows;
  const focusRow = (index: number) => {
    const next = Math.max(0, Math.min(rows.length - 1, index));
    setActive(next);
    bodyRef.current?.querySelector<HTMLElement>(`[data-row="${next}"]`)?.focus();
  };

  return (
    <table
      role="grid"
      aria-label={label}
      aria-busy={loading || undefined}
      className="w-full border-separate border-spacing-0 text-[12.5px]"
    >
      <thead className="sticky top-0 z-10 bg-secondary">
        {table.getHeaderGroups().map((group) => (
          <tr key={group.id}>
            {group.headers.map((header) => {
              const meta = (header.column.columnDef.meta ?? {}) as ColumnMeta;
              const sorted = header.column.getIsSorted();
              return (
                <th
                  key={header.id}
                  aria-sort={
                    sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined
                  }
                  className={cn(
                    "border-b px-3 py-1.5 text-left text-[11px] font-semibold tracking-wide whitespace-nowrap text-muted-foreground uppercase",
                    meta.align === "right" && "text-right",
                    meta.className,
                  )}
                >
                  {header.column.getCanSort() ? (
                    <button
                      type="button"
                      onClick={header.column.getToggleSortingHandler()}
                      className="inline-flex items-center gap-1 uppercase hover:text-foreground"
                    >
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {sorted === "asc" && <ArrowUp className="size-3" aria-hidden />}
                      {sorted === "desc" && <ArrowDown className="size-3" aria-hidden />}
                    </button>
                  ) : (
                    flexRender(header.column.columnDef.header, header.getContext())
                  )}
                </th>
              );
            })}
          </tr>
        ))}
      </thead>
      <tbody ref={bodyRef}>
        {rows.map((row, i) => (
          <tr
            key={row.id}
            data-row={i}
            tabIndex={i === Math.min(active, rows.length - 1) ? 0 : -1}
            onClick={() => {
              setActive(i);
              onOpen?.(row.original);
            }}
            onKeyDown={(e) => {
              const target = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: rows.length - 1 }[
                e.key
              ];
              if (target !== undefined) {
                e.preventDefault();
                focusRow(target);
              } else if (e.key === "Enter" && onOpen) {
                e.preventDefault();
                onOpen(row.original);
              }
            }}
            className={cn(
              "outline-none hover:bg-card focus-visible:bg-card focus-visible:shadow-[inset_3px_0_0_var(--ring)]",
              onOpen && "cursor-pointer",
              rowClassName?.(row.original),
            )}
          >
            {row.getVisibleCells().map((cell) => {
              const meta = (cell.column.columnDef.meta ?? {}) as ColumnMeta;
              return (
                <td
                  key={cell.id}
                  className={cn(
                    "h-8 border-b px-3 align-middle",
                    meta.align === "right" && "text-right tabular-nums",
                    meta.className,
                  )}
                >
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              );
            })}
          </tr>
        ))}
        {!rows.length && (
          <tr>
            <td colSpan={columns.length} className="px-3 py-10 text-center text-muted-foreground">
              {loading ? (
                <span role="status" className="inline-flex items-center gap-2">
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                  {t("common.loading")}
                </span>
              ) : error ? (
                <span role="alert" className="text-destructive">
                  {tr(error.message)}
                </span>
              ) : (
                t("common.none")
              )}
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

export function SearchInput({
  value,
  onChange,
  placeholder,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  className?: string;
}) {
  return (
    <input
      type="search"
      data-search
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={`${placeholder}  /`}
      aria-label={placeholder}
      aria-keyshortcuts="/"
      className={cn(
        "h-8 w-64 rounded-md border border-input bg-card px-2.5 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/40",
        className,
      )}
    />
  );
}

export function Toolbar({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-2 border-b bg-card px-4 py-2">
      {children}
    </div>
  );
}
