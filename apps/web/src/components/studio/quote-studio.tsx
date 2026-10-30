"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useMutationState } from "@tanstack/react-query";
import type { ItemUpdate, QuoteDetail } from "@zuschlag/api-types";
import { BadgeCheck, Calculator, FileDown, Loader2, Lock, Send, TriangleAlert } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { QuoteStatusBadge } from "@/components/status-badge";
import { BomTable } from "@/components/studio/bom-table";
import { IdocDialog } from "@/components/studio/idoc-dialog";
import { RfqPanel } from "@/components/studio/rfq-panel";
import { ZuschlagControl, type TermsState } from "@/components/studio/zuschlag-control";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { Tooltip } from "@/components/ui/tooltip";
import { useI18n } from "@/i18n";
import { useServerText } from "@/lib/server-messages";
import { BASE_PATH } from "@/lib/demo/config";
import { ApiError } from "@/lib/api/client";
import { useApprove, useCalculate, useQuote, useUpdateItem } from "@/lib/api/queries";
import { Dec } from "@/lib/decimal";
import { formatDate } from "@/lib/format";
import { useShortcuts } from "@/lib/keyboard";
import type { VatPercent } from "@/lib/pricing";
import { clampPct, totalsFor, vatOf, withTotals } from "@/lib/quote-math";

export function QuoteStudio({ id }: { id: string }) {
  const { t } = useI18n();
  const tr = useServerText();
  const { data: quote, error, isLoading, refetch } = useQuote(id);

  if (isLoading) {
    return (
      <>
        <PageHeader title={t("quotes.title")} />
        <p role="status" className="flex items-center gap-2 p-6 text-muted-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          {t("common.loading")}
        </p>
      </>
    );
  }
  if (!quote) {
    return (
      <>
        <PageHeader title={t("quotes.title")} />
        <div role="alert" className="m-6 rounded-md border border-destructive/40 p-4">
          <p className="font-medium text-destructive">
            {error ? tr(error.message) : t("common.error")}
          </p>
          <Link href="/quotes" className="mt-2 inline-block text-sm text-accent underline">
            {t("quotes.back")}
          </Link>
          <Button className="mt-3" size="sm" variant="outline" onClick={() => void refetch()}>
            {t("common.retry")}
          </Button>
        </div>
      </>
    );
  }
  return <Studio quote={quote} />;
}

function initialTerms(quote: QuoteDetail): TermsState {
  const agreed = quote.customer?.agreed_payment_terms ?? [];
  const zterm = quote.payment_terms ?? agreed[0] ?? "";
  return {
    zterm,
    allowDeviation: Boolean(
      quote.payment_terms && agreed.length && !agreed.includes(quote.payment_terms),
    ),
  };
}

function Studio({ quote }: { quote: QuoteDetail }) {
  const { t, locale } = useI18n();
  const tr = useServerText();
  const toast = useToast();
  const locked = quote.status === "synced";

  // ------------------------------------------------ Zuschlag / VAT / terms draft
  const [draft, setDraft] = useState<{ pct: Dec; vat: VatPercent } | null>(null);
  const [terms, setTerms] = useState<TermsState>(() => initialTerms(quote));
  const [changes, setChanges] = useState(0);
  const calc = useCalculate(quote.id);
  const pct = draft?.pct ?? clampPct(Dec.from(quote.margin_pct));
  const vat = draft?.vat ?? vatOf(quote);
  const totals = useMemo(() => totalsFor(quote, pct, vat), [quote, pct, vat]);
  const shown = useMemo(() => (draft ? withTotals(quote, totals) : quote), [draft, quote, totals]);

  const latest = useRef({ pct, vat, terms });
  latest.current = { pct, vat, terms };
  const { mutate: calculate } = calc;
  const commit = useCallback(() => {
    const { pct, vat, terms } = latest.current;
    calculate(
      {
        zuschlag_pct: pct.toFixed(),
        vat_rate: vat,
        payment_terms: terms.zterm || undefined,
        allow_terms_deviation: terms.allowDeviation,
      },
      {
        onError: (e) => {
          toast({ kind: "error", title: t("common.error"), detail: e.message });
          setDraft(null);
        },
      },
    );
  }, [calculate, t, toast]);

  // Commit 450 ms after the last change (slider drags produce many).
  useEffect(() => {
    if (!changes) return;
    const timer = setTimeout(commit, 450);
    return () => clearTimeout(timer);
  }, [changes, commit]);

  // Drop the draft once the server has the same values.
  useEffect(() => {
    if (
      draft &&
      !calc.isPending &&
      Dec.from(quote.margin_pct).eq(draft.pct) &&
      vatOf(quote) === draft.vat
    )
      setDraft(null);
  }, [quote, draft, calc.isPending]);

  const onZuschlag = (nextPct: Dec, nextVat: VatPercent) => {
    setDraft({ pct: nextPct, vat: nextVat });
    setChanges((n) => n + 1);
  };
  const onTerms = (next: TermsState) => {
    setTerms(next);
    if (/^[A-Z0-9]{4}$/.test(next.zterm) || next.zterm === "") setChanges((n) => n + 1);
  };

  // ------------------------------------------------ inline edits
  const update = useUpdateItem(quote.id);
  const pending = useMutationState({
    filters: { mutationKey: ["update-item", quote.id], status: "pending" },
    select: (m) => (m.state.variables as { itemId: string } | undefined)?.itemId,
  });
  const pendingItemIds = useMemo(() => new Set(pending.filter(Boolean) as string[]), [pending]);
  const onEdit = (itemId: string, patch: ItemUpdate) =>
    update.mutate(
      { itemId, patch },
      {
        onError: (e) => toast({ kind: "error", title: t("studio.saveFailed"), detail: e.message }),
      },
    );

  // ------------------------------------------------ approve / sync / print
  const approve = useApprove(quote.id);
  const [syncOpen, setSyncOpen] = useState(false);
  const approveBlocked = quote.approve_blockers.length > 0 || quote.status === "approved" || locked;
  const syncBlocked = quote.export_blockers.length > 0;

  const doApprove = () => {
    if (quote.status === "approved" || locked) return;
    if (quote.approve_blockers.length) {
      toast({ kind: "error", title: t("studio.blockers"), detail: quote.approve_blockers });
      return;
    }
    approve.mutate(undefined, {
      onSuccess: () => toast({ kind: "success", title: t("studio.approved") }),
      onError: (e) =>
        toast({
          kind: "error",
          title: t("common.error"),
          detail: e instanceof ApiError && e.reasons.length ? e.reasons : e.message,
        }),
    });
  };
  const doSync = () => {
    if (syncBlocked) {
      toast({ kind: "error", title: t("studio.blockers"), detail: quote.export_blockers });
      return;
    }
    setSyncOpen(true);
  };
  const printHref = `/quotes/${quote.id}/print`;

  useShortcuts([
    {
      combo: "z",
      handler: () => document.querySelector<HTMLInputElement>("[data-zuschlag-input]")?.focus(),
      enabled: !locked,
    },
    { combo: "shift+a", handler: doApprove },
    { combo: "shift+s", handler: doSync },
    {
      combo: "shift+p",
      handler: () => window.open(`${BASE_PATH}${printHref}`, "_blank", "noopener"),
    },
  ]);

  return (
    <>
      <PageHeader
        documentTitle={`${quote.quote_number} · ${t("quotes.title")}`}
        title={
          <span className="flex items-center gap-2">
            <Link
              href="/quotes"
              className="hidden text-muted-foreground hover:text-foreground sm:inline"
            >
              {t("quotes.title")}
            </Link>
            <span aria-hidden className="hidden text-muted-foreground sm:inline">
              /
            </span>
            <span className="font-mono">{quote.quote_number}</span>
            <span
              className="rounded border px-1 font-mono text-[11px] text-muted-foreground"
              title={t("studio.revision")}
            >
              v{quote.revision}
            </span>
          </span>
        }
        meta={
          <>
            <QuoteStatusBadge status={quote.status} />
            <span className="hidden truncate text-xs text-muted-foreground xl:inline">
              {quote.customer ? (
                <>
                  {quote.customer.name1} · <span className="font-mono">{quote.customer.kunnr}</span>
                </>
              ) : (
                quote.customer_name
              )}
              {quote.requested_delivery_date &&
                ` · ${t("quotes.delivery")} ${formatDate(quote.requested_delivery_date, locale)}`}
            </span>
          </>
        }
      />

      {/* Below lg the panels stack and the page scrolls; from lg it is the split screen. */}
      <div className="min-h-0 flex-1 overflow-y-auto lg:grid lg:grid-cols-[clamp(280px,28%,560px)_minmax(0,1fr)] lg:overflow-hidden">
        <RfqPanel quote={quote} />

        <section aria-labelledby="bom-heading" className="flex min-w-0 flex-col lg:min-h-0">
          <div className="flex min-h-10 shrink-0 flex-wrap items-center gap-2 border-b bg-card px-3 py-1.5 [&_[data-slot=button]]:text-xs">
            <h2
              id="bom-heading"
              className="text-xs font-semibold tracking-wide text-muted-foreground uppercase"
            >
              {t("studio.bomPanel")}
            </h2>
            {locked ? (
              <Badge variant="accent">
                <Lock aria-hidden />
                {t("studio.synced", { docnum: quote.last_idoc_docnum ?? "" })}
              </Badge>
            ) : (
              <Blockers quote={quote} />
            )}
            {quote.status === "approved" && (
              <span className="flex items-center gap-1 text-xs text-muted-foreground">
                <Lock className="size-3" aria-hidden />
                {t("studio.frozen", { next: `v${quote.revision + 1}` })}
              </span>
            )}
            <div className="ml-auto flex flex-wrap items-center gap-1.5">
              {!quote.calculated_at && !locked && (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7"
                  onClick={commit}
                  disabled={calc.isPending}
                >
                  <Calculator aria-hidden />
                  {t("studio.applyCalc")}
                </Button>
              )}
              <Button asChild size="sm" variant="outline" className="h-7">
                <a
                  href={`${BASE_PATH}${printHref}`}
                  target="_blank"
                  rel="noopener"
                  aria-keyshortcuts="Shift+P"
                >
                  <FileDown aria-hidden />
                  {t("studio.exportPdf")}
                </a>
              </Button>
              <Tooltip
                content={
                  approveBlocked && quote.approve_blockers.length ? (
                    <List items={quote.approve_blockers} />
                  ) : null
                }
              >
                <Button
                  size="sm"
                  variant={quote.status === "approved" ? "outline" : "default"}
                  className="h-7"
                  aria-disabled={approveBlocked || approve.isPending}
                  data-disabled={approveBlocked || undefined}
                  onClick={doApprove}
                  aria-keyshortcuts="Shift+A"
                  aria-describedby={quote.approve_blockers.length ? "approve-blockers" : undefined}
                >
                  {approve.isPending ? (
                    <Loader2 className="animate-spin" aria-hidden />
                  ) : (
                    <BadgeCheck aria-hidden />
                  )}
                  {quote.status === "approved" ? t("status.approved") : t("studio.approve")}
                </Button>
              </Tooltip>
              <Tooltip
                content={syncBlocked && !locked ? <List items={quote.export_blockers} /> : null}
              >
                <Button
                  size="sm"
                  variant="accent"
                  className="h-7"
                  aria-disabled={syncBlocked}
                  data-disabled={syncBlocked || undefined}
                  onClick={doSync}
                  aria-keyshortcuts="Shift+S"
                  aria-haspopup="dialog"
                >
                  <Send aria-hidden />
                  {t("studio.sync")}
                </Button>
              </Tooltip>
            </div>
            <ul id="approve-blockers" className="sr-only">
              {quote.approve_blockers.map((b) => (
                <li key={b}>{tr(b)}</li>
              ))}
            </ul>
          </div>

          <div className="min-h-40 overflow-x-auto bg-background lg:min-h-0 lg:flex-1 lg:overflow-auto">
            <BomTable
              items={shown.items}
              currency={quote.currency}
              locked={locked}
              pendingItemIds={pendingItemIds}
              onEdit={onEdit}
            />
          </div>

          <ZuschlagControl
            quote={quote}
            totals={totals}
            pct={pct}
            vat={vat}
            terms={terms}
            locked={locked}
            state={calc.isPending || draft ? "pending" : calc.isError ? "error" : "idle"}
            onChange={onZuschlag}
            onTerms={onTerms}
          />
        </section>
      </div>

      <IdocDialog quote={quote} open={syncOpen} onOpenChange={setSyncOpen} />
    </>
  );
}

function Blockers({ quote }: { quote: QuoteDetail }) {
  const { t } = useI18n();
  const open = quote.status === "approved" ? quote.export_blockers : quote.approve_blockers;
  if (!open.length) return null;
  return (
    <Tooltip content={<List items={open} />}>
      <button
        type="button"
        className="flex items-center gap-1 rounded text-xs text-warning-foreground hover:underline"
      >
        <TriangleAlert className="size-3.5" aria-hidden />
        {t("studio.blockers")} {open.length}
      </button>
    </Tooltip>
  );
}

function List({ items }: { items: string[] }) {
  const tr = useServerText();
  return (
    <ul className="list-disc space-y-0.5 pl-4">
      {items.map((i) => (
        <li key={i}>{tr(i)}</li>
      ))}
    </ul>
  );
}
