"use client";

import { useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { QuoteDetail } from "@zuschlag/api-types";
import {
  FileText,
  Loader2,
  Mail,
  Paperclip,
  RotateCw,
  ScanText,
  TriangleAlert,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/i18n";
import { ApiError } from "@/lib/api/client";
import { useReparse } from "@/lib/api/queries";
import { findEntities, segments, type Entity } from "@/lib/entities";
import { formatDateTime } from "@/lib/format";
import { useShortcuts } from "@/lib/keyboard";
import { cn } from "@/lib/utils";

type Tab = "email" | "attachments" | "entities";

const KIND_STYLE: Record<Entity["kind"], string> = {
  party: "bg-accent/15 text-accent",
  item: "bg-warning/25 text-warning-foreground",
  spec: "bg-success/15 text-success-foreground",
  date: "bg-[oklch(0.6_0.2_300/14%)] text-[oklch(0.45_0.2_300)]",
};

export function RfqPanel({ quote }: { quote: QuoteDetail }) {
  const { t, locale } = useI18n();
  const [tab, setTab] = useState<Tab>("email");
  const bodyRef = useRef<HTMLDivElement>(null);
  const rfq = quote.rfq;
  const body = rfq?.body_text ?? "";
  const entities = useMemo(() => findEntities(quote.extraction, body), [quote.extraction, body]);
  const parts = useMemo(() => segments(body, entities), [body, entities]);
  const extraction = quote.extraction as {
    customer?: { contact_name?: string; contact_email?: string };
  } | null;

  const tabs: Array<{ id: Tab; label: string; icon: typeof Mail; count?: number }> = [
    { id: "email", label: t("studio.email"), icon: Mail },
    {
      id: "attachments",
      label: t("studio.attachments"),
      icon: Paperclip,
      count: rfq?.attachment_object_key ? 1 : 0,
    },
    { id: "entities", label: t("studio.entities"), icon: ScanText, count: entities.length },
  ];

  const reveal = (entity: Entity) => {
    setTab("email");
    requestAnimationFrame(() => {
      const mark = bodyRef.current?.querySelector<HTMLElement>(`[data-entity-id="${entity.id}"]`);
      mark?.scrollIntoView({ block: "center", behavior: "smooth" });
      mark?.focus();
    });
  };

  return (
    <section aria-labelledby="rfq-heading" className="flex min-h-0 flex-col border-r bg-card">
      <div className="flex h-10 shrink-0 items-center gap-2 border-b px-3">
        <h2
          id="rfq-heading"
          className="text-xs font-semibold tracking-wide text-muted-foreground uppercase"
        >
          {t("studio.rfqPanel")}
        </h2>
        <ReparseButton quote={quote} />
      </div>

      <div
        role="tablist"
        aria-label={t("studio.rfqPanel")}
        className="flex shrink-0 gap-1 border-b px-2"
      >
        {tabs.map(({ id, label, icon: Icon, count }) => (
          <button
            key={id}
            role="tab"
            id={`rfq-tab-${id}`}
            aria-selected={tab === id}
            aria-controls={`rfq-panel-${id}`}
            tabIndex={tab === id ? 0 : -1}
            onClick={() => setTab(id)}
            onKeyDown={(e) => {
              const i = tabs.findIndex((x) => x.id === tab);
              if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                const next =
                  tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length]!;
                setTab(next.id);
                document.getElementById(`rfq-tab-${next.id}`)?.focus();
              }
            }}
            className={cn(
              "-mb-px flex items-center gap-1.5 border-b-2 px-2 py-2 text-xs font-medium focus-visible:bg-secondary focus-visible:outline-none",
              tab === id
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-3.5" aria-hidden />
            {label}
            {count !== undefined && (
              <span className="rounded bg-secondary px-1 text-[10px] tabular-nums">{count}</span>
            )}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === "email" && (
          <div role="tabpanel" id="rfq-panel-email" aria-labelledby="rfq-tab-email" className="p-3">
            <dl className="mb-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-md border bg-background p-2.5 text-xs">
              <dt className="text-muted-foreground">{t("studio.from")}</dt>
              <dd className="truncate">
                {extraction?.customer?.contact_name ?? quote.contact_name ?? "—"}
                {(extraction?.customer?.contact_email ?? quote.contact_email) && (
                  <span className="text-muted-foreground">
                    {" "}
                    &lt;{extraction?.customer?.contact_email ?? quote.contact_email}&gt;
                  </span>
                )}
              </dd>
              <dt className="text-muted-foreground">{t("studio.receivedAt")}</dt>
              <dd>{formatDateTime(rfq?.received_at, locale)}</dd>
              <dt className="text-muted-foreground">{t("studio.subject")}</dt>
              <dd className="font-medium">{rfq?.subject ?? "—"}</dd>
            </dl>
            {body ? (
              <>
                <Legend />
                <div
                  ref={bodyRef}
                  tabIndex={0}
                  aria-label={t("studio.email")}
                  className="rounded-md border bg-background p-3 font-mono text-[12px] leading-relaxed whitespace-pre-wrap focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                >
                  {parts.map((part, i) =>
                    part.entity ? (
                      <mark
                        key={i}
                        tabIndex={-1}
                        data-entity={part.entity.kind}
                        data-entity-id={part.entity.id}
                        title={t(part.entity.label)}
                        className="focus:outline-2 focus:outline-ring"
                      >
                        {part.text}
                      </mark>
                    ) : (
                      <span key={i}>{part.text}</span>
                    ),
                  )}
                </div>
              </>
            ) : (
              <p className="text-muted-foreground">{t("studio.noBody")}</p>
            )}
          </div>
        )}

        {tab === "attachments" && (
          <div
            role="tabpanel"
            id="rfq-panel-attachments"
            aria-labelledby="rfq-tab-attachments"
            className="p-3"
          >
            {rfq?.attachment_object_key ? (
              <div className="flex gap-3 rounded-md border bg-background p-3">
                <FileText className="size-8 shrink-0 text-destructive" aria-hidden />
                <div className="min-w-0">
                  <p className="truncate font-mono text-xs font-medium">
                    {rfq.attachment_object_key.split("/").pop()}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("studio.attachmentStored")}
                  </p>
                </div>
              </div>
            ) : (
              <p className="text-muted-foreground">{t("studio.noAttachments")}</p>
            )}
          </div>
        )}

        {tab === "entities" && (
          <div
            role="tabpanel"
            id="rfq-panel-entities"
            aria-labelledby="rfq-tab-entities"
            className="p-3"
          >
            <ul className="space-y-1">
              {entities.map((e) => (
                <li key={e.id}>
                  <button
                    type="button"
                    disabled={!e.ranges.length}
                    onClick={() => reveal(e)}
                    className="flex w-full items-start gap-2 rounded px-1.5 py-1 text-left hover:bg-secondary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:cursor-default disabled:hover:bg-transparent"
                  >
                    <span
                      className={cn(
                        "mt-px shrink-0 rounded px-1.5 py-px text-[10px] font-medium",
                        KIND_STYLE[e.kind],
                      )}
                    >
                      {t(e.label)}
                    </span>
                    <span className="min-w-0 flex-1 break-words">{e.text}</span>
                    {!e.ranges.length && (
                      <span className="shrink-0 text-[10px] text-muted-foreground italic">
                        {t("studio.notInText")}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
            {quote.review_reasons.length > 0 && (
              <div className="mt-4">
                <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-warning-foreground">
                  <TriangleAlert className="size-3.5" aria-hidden />
                  {t("studio.reviewReasons")}
                </h3>
                <ul className="list-disc space-y-1 pl-5 text-xs">
                  {quote.review_reasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function Legend() {
  const { t } = useI18n();
  const items: Array<[Entity["kind"], string]> = [
    ["party", t("studio.entity.company")],
    ["item", t("studio.entity.item")],
    ["spec", t("studio.entity.spec")],
    ["date", t("studio.entity.delivery")],
  ];
  return (
    <div
      className="mb-2 flex flex-wrap items-center gap-1.5 text-[10px]"
      aria-label={t("studio.legend")}
    >
      {items.map(([kind, label]) => (
        <span key={kind} className={cn("rounded px-1.5 py-px font-medium", KIND_STYLE[kind])}>
          {label}
        </span>
      ))}
    </div>
  );
}

function ReparseButton({ quote }: { quote: QuoteDetail }) {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const reparse = useReparse(quote.id);
  const disabled = !quote.rfq?.body_text || quote.status === "synced" || reparse.isPending;

  const run = () => {
    if (disabled) return;
    reparse.mutate(undefined, {
      onSuccess: (next) => {
        toast({ kind: "success", title: t("studio.reparsed", { number: next.quote_number }) });
        router.push(`/quotes/${next.id}`);
      },
      onError: (e) => toast({ kind: "error", title: t("studio.reparseFailed"), detail: e.message }),
    });
  };
  useShortcuts([{ combo: "shift+r", handler: run }]);

  return (
    <div className="ml-auto flex items-center gap-2">
      <span role="status" aria-live="polite" className="text-[11px]">
        {reparse.isPending && (
          <span className="text-muted-foreground">{t("studio.reparsing")}</span>
        )}
        {reparse.isError && (
          <Badge variant="destructive" title={reparse.error.message}>
            {reparse.error instanceof ApiError ? `HTTP ${reparse.error.status}` : t("common.error")}
          </Badge>
        )}
      </span>
      <Button
        variant="outline"
        size="sm"
        onClick={run}
        disabled={disabled}
        aria-keyshortcuts="Shift+R"
        className="h-7"
      >
        {reparse.isPending ? (
          <Loader2 className="animate-spin" aria-hidden />
        ) : (
          <RotateCw aria-hidden />
        )}
        {t("studio.reparse")}
      </Button>
    </div>
  );
}
