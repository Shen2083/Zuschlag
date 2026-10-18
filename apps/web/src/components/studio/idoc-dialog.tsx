"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { QuoteDetail } from "@zuschlag/api-types";
import {
  Check,
  Copy,
  Download,
  Loader2,
  RotateCw,
  Send,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/i18n";
import { ApiError } from "@/lib/api/client";
import { usePrepareIdoc, useSendIdoc } from "@/lib/api/queries";
import { formatNumber } from "@/lib/format";

/**
 * Shows the exact ORDERS05/REQOTE bytes before they go to SAP. "Send" posts the
 * DOCNUM and SHA-256 of what is displayed; the API re-renders the IDoc and refuses
 * (409) if a single byte differs, so what the estimator approved is what SAP gets.
 */
export function IdocDialog({
  quote,
  open,
  onOpenChange,
}: {
  quote: QuoteDetail;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t, locale } = useI18n();
  const toast = useToast();
  const prepare = usePrepareIdoc(quote.id);
  const send = useSendIdoc(quote.id);
  const [copied, setCopied] = useState(false);
  const preview = prepare.data;

  const { mutate: prepareMutate, reset: resetPrepare } = prepare;
  const { reset: resetSend } = send;
  // Each preview reserves a DOCNUM: request exactly one per opening (also under StrictMode).
  const requested = useRef(false);
  useEffect(() => {
    if (open && !requested.current) {
      requested.current = true;
      prepareMutate();
    } else if (!open) {
      requested.current = false;
      resetPrepare();
      resetSend();
    }
  }, [open, prepareMutate, resetPrepare, resetSend]);

  const lines = useMemo(() => preview?.xml.split("\r\n") ?? [], [preview]);
  const bytes = useMemo(() => (preview ? new TextEncoder().encode(preview.xml) : null), [preview]);
  const stale = send.error instanceof ApiError && send.error.status === 409;

  const download = () => {
    if (!preview || !bytes) return;
    const url = URL.createObjectURL(new Blob([bytes], { type: "application/xml" }));
    const a = Object.assign(document.createElement("a"), {
      href: url,
      download: `REQOTE_${preview.docnum}.xml`,
    });
    a.click();
    URL.revokeObjectURL(url);
  };

  const copy = async () => {
    if (!preview) return;
    await navigator.clipboard.writeText(preview.xml);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const submit = () => {
    if (!preview) return;
    send.mutate(
      { docnum: preview.docnum, sha256: preview.sha256 },
      {
        onSuccess: (result) => {
          toast({
            kind: "success",
            title: t("idoc.sent", { docnum: result.docnum, reference: result.reference }),
            detail: result.sap_status.length
              ? result.sap_status.map((s) => `SAP ${s.status}: ${s.text ?? ""}`)
              : undefined,
          });
          onOpenChange(false);
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        closeLabel={t("common.close")}
        className="max-w-4xl"
        aria-describedby="idoc-description"
      >
        <DialogTitle>
          {t("idoc.title")} · <span className="font-mono">ORDERS05 / REQOTE</span>
        </DialogTitle>
        <DialogDescription id="idoc-description">{t("idoc.description")}</DialogDescription>

        {prepare.isPending && (
          <p role="status" className="flex items-center gap-2 py-10 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            {t("idoc.preparing")}
          </p>
        )}

        {prepare.isError && (
          <div
            role="alert"
            className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm"
          >
            <p className="font-medium text-destructive">{prepare.error.message}</p>
            {prepare.error instanceof ApiError && prepare.error.reasons.length > 0 && (
              <ul className="mt-1 list-disc pl-5 text-xs">
                {prepare.error.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {preview && bytes && (
          <>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-4">
              <Meta label={t("idoc.docnum")} value={preview.docnum} mono />
              <Meta label={t("idoc.receiver")} value={preview.receiver} mono />
              <Meta
                label={t("idoc.transport")}
                value={preview.transport ? t(`idoc.transports.${preview.transport}`) : "—"}
              />
              <Meta
                label={t("idoc.payload")}
                value={`${t("idoc.bytes", { count: formatNumber(bytes.length, locale) })} · UTF-8 · CRLF`}
              />
              <div className="col-span-full flex items-center gap-2">
                <dt className="text-muted-foreground">{t("idoc.sha")}</dt>
                <dd className="truncate font-mono text-[11px]">{preview.sha256}</dd>
                <dd className="ml-auto flex shrink-0 items-center gap-1 text-success">
                  <ShieldCheck className="size-3.5" aria-hidden />
                  {t("idoc.xsd")}
                </dd>
              </div>
            </dl>

            <pre
              tabIndex={0}
              aria-label={t("idoc.payload")}
              className="min-h-0 flex-1 overflow-auto rounded-md border bg-[oklch(0.17_0.03_265)] p-3 font-mono text-[12px] leading-[1.55] text-[oklch(0.9_0.02_250)] focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              <code>
                {lines.map((line, i) => (
                  <span key={i} className="flex">
                    <span
                      aria-hidden
                      className="w-9 shrink-0 pr-3 text-right text-[oklch(0.72_0.03_250)] select-none"
                    >
                      {i + 1}
                    </span>
                    <span className="whitespace-pre">{line}</span>
                  </span>
                ))}
              </code>
            </pre>

            {!preview.transport && (
              <p className="flex items-center gap-2 text-xs text-warning-foreground">
                <TriangleAlert className="size-3.5" aria-hidden />
                {t("idoc.noTransport")}
              </p>
            )}
            {send.isError && (
              <div
                role="alert"
                className="flex items-center gap-3 rounded-md border border-destructive/40 bg-destructive/5 p-2.5 text-sm"
              >
                <TriangleAlert className="size-4 shrink-0 text-destructive" aria-hidden />
                <div className="flex-1">
                  <p>{stale ? `${t("idoc.stale")} ${send.error.message}` : send.error.message}</p>
                  {send.error instanceof ApiError && send.error.reasons.length > 0 && (
                    <ul className="mt-1 list-disc pl-5 text-xs">
                      {send.error.reasons.map((r) => (
                        <li key={r}>{r}</li>
                      ))}
                    </ul>
                  )}
                </div>
                {stale && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => (resetSend(), prepareMutate())}
                  >
                    <RotateCw aria-hidden />
                    {t("idoc.regenerate")}
                  </Button>
                )}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => void copy()}>
                {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
                {copied ? t("common.copied") : t("common.copy")}
              </Button>
              <Button variant="outline" size="sm" onClick={download}>
                <Download aria-hidden />
                {t("common.download")}
              </Button>
              <div className="ml-auto flex gap-2">
                <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
                  {t("common.cancel")}
                </Button>
                <Button
                  variant="accent"
                  size="sm"
                  onClick={submit}
                  disabled={!preview.transport || send.isPending || stale}
                >
                  {send.isPending ? (
                    <Loader2 className="animate-spin" aria-hidden />
                  ) : (
                    <Send aria-hidden />
                  )}
                  {send.isPending ? t("idoc.sending") : t("idoc.send")}
                </Button>
              </div>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Meta({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={mono ? "truncate font-mono" : "truncate"}>{value}</dd>
    </div>
  );
}
