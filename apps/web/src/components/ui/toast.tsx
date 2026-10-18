"use client";

import * as React from "react";
import { CheckCircle2, CircleAlert, X } from "lucide-react";

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

/** Announced via aria-live; errors stay until dismissed, successes fade after 5 s. */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);
  const nextId = React.useRef(0);
  const dismiss = React.useCallback(
    (id: number) => setToasts((all) => all.filter((t) => t.id !== id)),
    [],
  );
  const push = React.useCallback(
    (toast: Omit<Toast, "id">) => {
      const id = ++nextId.current;
      setToasts((all) => [...all.slice(-3), { ...toast, id }]);
      if (toast.kind === "success") setTimeout(() => dismiss(id), 5000);
    },
    [dismiss],
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
