"use client";

import { RefreshCw } from "lucide-react";

import { Tooltip } from "@/components/ui/tooltip";
import { useI18n } from "@/i18n";
import { useSapStatus } from "@/lib/api/queries";
import { formatDateTime, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

const DOT = {
  connected: "bg-success",
  unreachable: "bg-destructive",
  not_configured: "bg-muted-foreground",
} as const;

/** Header indicator: SAP connection state, system ID / client and latency. */
export function SapStatusIndicator() {
  const { t, locale } = useI18n();
  const { data, isFetching, isError, refetch } = useSapStatus();
  const state = isError ? "unreachable" : (data?.state ?? null);
  const label = state ? t(`sap.${state}`) : t("sap.checking");
  const ms = (v: number | null | undefined) =>
    v === null || v === undefined
      ? "—"
      : v < 1
        ? "<1 ms"
        : `${formatNumber(v, locale, { maxFrac: v < 10 ? 1 : 0 })} ms`;

  const details = data && (
    <dl className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5">
      <dt className="opacity-70">{t("sap.transport")}</dt>
      <dd>
        {data.transport ? t(`idoc.transports.${data.transport}`) : "—"} · {data.detail}
      </dd>
      <dt className="opacity-70">{t("sap.lastInbound")}</dt>
      <dd>{formatDateTime(data.last_inbound_at, locale)}</dd>
      <dt className="opacity-70">{t("sap.lastOutbound")}</dt>
      <dd>{formatDateTime(data.last_outbound_at, locale)}</dd>
    </dl>
  );

  return (
    <div className="flex items-center gap-1" role="status" aria-live="polite">
      <Tooltip content={details} side="bottom">
        <div
          tabIndex={0}
          className="flex h-7 items-center gap-2 rounded-md border bg-card px-2.5 text-xs whitespace-nowrap focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <span className="relative flex size-2">
            {state === "connected" && (
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-40 motion-reduce:hidden" />
            )}
            <span
              className={cn(
                "relative inline-flex size-2 rounded-full",
                state ? DOT[state] : "bg-muted-foreground",
              )}
            />
          </span>
          <span className="font-medium">
            {t("sap.label")}: {label}
          </span>
          {data?.system_id && (
            <span
              className="hidden border-l pl-2 font-mono text-muted-foreground lg:inline"
              title={t("sap.system")}
            >
              {data.system_id}
              {data.client && <span aria-label={t("sap.client")}> / {data.client}</span>}
            </span>
          )}
          <span className="hidden border-l pl-2 font-mono text-muted-foreground tabular-nums 2xl:inline">
            {t("sap.latency")} {ms(data?.latency_ms)}
            <span>
              {" "}
              · {t("sap.apiLatency")} {ms(data?.apiLatencyMs)}
            </span>
          </span>
        </div>
      </Tooltip>
      <button
        type="button"
        onClick={() => void refetch()}
        className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
        aria-label={t("sap.refresh")}
      >
        <RefreshCw className={cn("size-3.5", isFetching && "animate-spin")} aria-hidden />
      </button>
    </div>
  );
}
