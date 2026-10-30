"use client";

import * as React from "react";
import { CheckCircle2, CircleAlert, X } from "lucide-react";

import { useServerText } from "@/lib/server-messages";
import { cn } from "@/lib/utils";

interface Toast {
  id: number;
  kind: "success" | "error";
  title: string;
  detail?: string | string[];
}

const ToastContext = React.createContext<(t: Omit<Toast, "id">) => void>(() => {});

export function useToast() {
  return React.useContext(ToastContext);
}

/**
 * Announced via aria-live. Successes fade after 5 s and clear older errors;
 * errors fade after 12 s and an identical error replaces itself instead of
 * stacking. Server messages in details are shown in the UI language.
 */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);
  const nextId = React.useRef(0);
  const dismiss = React.useCallback(
    (id: number) => setToasts((all) => all.filter((t) => t.id !== id)),
    [],
  );
  const tr = useServerText();
  const push = React.useCallback(
    (toast: Omit<Toast, "id">) => {
      const id = ++nextId.current;
      const detail = Array.isArray(toast.detail)
        ? toast.detail.map(tr)
        : toast.detail
          ? tr(toast.detail)
          : undefined;
      const next = { ...toast, title: tr(toast.title), detail, id };
      const key = (t: Toast) => `${t.kind}|${t.title}|${JSON.stringify(t.detail)}`;
      setToasts((all) => {
        const kept = all.filter((t) =>
          toast.kind === "success" ? t.kind === "success" : key(t) !== key(next),
        );
        return [...kept.slice(-2), next];
      });
      setTimeout(() => dismiss(id), toast.kind === "success" ? 5000 : 12000);
    },
    [dismiss, tr],
  );
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed right-4 bottom-4 z-[60] flex w-96 max-w-[calc(100%-2rem)] flex-col gap-2 print:hidden"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role={t.kind === "error" ? "alert" : "status"}
            className={cn(
              "pointer-events-auto flex gap-2.5 rounded-md border bg-card p-3 text-sm shadow-lg",
              t.kind === "error" ? "border-destructive/40" : "border-success/40",
            )}
          >
            {t.kind === "error" ? (
              <CircleAlert className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
            ) : (
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
            )}
            <div className="min-w-0 flex-1">
              <p className="font-medium">{t.title}</p>
              {Array.isArray(t.detail) ? (
                <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                  {t.detail.map((d) => (
                    <li key={d}>{d}</li>
                  ))}
                </ul>
              ) : (
                t.detail && (
                  <p className="mt-0.5 text-xs break-words text-muted-foreground">{t.detail}</p>
                )
              )}
            </div>
            <button
              type="button"
              onClick={() => dismiss(t.id)}
              className="self-start rounded p-0.5 text-muted-foreground hover:text-foreground"
              aria-label="Dismiss"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
