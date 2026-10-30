"use client";

import { FlaskConical, RotateCcw } from "lucide-react";

import { useI18n } from "@/i18n";

const REPO = "https://github.com/Shen2083/Zuschlag";

/** Static demo only: says plainly what is simulated, and resets the browser state. */
export function DemoBanner() {
  const { t } = useI18n();
  const reset = async () => {
    (await import("@/lib/demo/api")).resetDemo();
    window.location.reload();
  };
  return (
    <div
      role="note"
      className="flex shrink-0 items-center gap-x-3 gap-y-1 border-b border-warning/40 bg-warning/15 px-3 py-1.5 text-xs sm:flex-wrap sm:px-4 print:hidden"
    >
      <FlaskConical className="size-3.5 shrink-0 text-warning-foreground" aria-hidden />
      <p className="min-w-0 flex-1">
        <strong>{t("demo.title")}</strong> <span className="sm:hidden">{t("demo.short")}</span>
        <span className="hidden sm:inline">{t("demo.body")}</span>
      </p>
      <button
        type="button"
        onClick={() => void reset()}
        className="flex items-center gap-1 rounded border border-warning/50 bg-card px-2 py-0.5 font-medium hover:bg-secondary"
      >
        <RotateCcw className="size-3" aria-hidden />
        <span className="sr-only sm:not-sr-only">{t("demo.reset")}</span>
      </button>
      <a
        href={REPO}
        target="_blank"
        rel="noopener"
        className="font-medium underline underline-offset-2"
      >
        {t("demo.source")}
      </a>
    </div>
  );
}
