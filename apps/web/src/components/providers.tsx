"use client";

import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setNonce } from "get-nonce";

import { TooltipProvider } from "@/components/ui/tooltip";
import { ToastProvider } from "@/components/ui/toast";
import { I18nProvider } from "@/i18n";
import { ApiError } from "@/lib/api/client";
import type { Locale } from "@/lib/format";

export function Providers({
  locale,
  nonce,
  children,
}: {
  locale: Locale;
  nonce?: string;
  children: React.ReactNode;
}) {
  // Radix dialogs lock scrolling with an injected <style>; the strict CSP only allows it with the nonce.
  if (nonce) setNonce(nonce);
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            refetchOnWindowFocus: true,
            // Client errors (404, 422) will not fix themselves.
            retry: (count, error) =>
              !(error instanceof ApiError && error.status < 500) && count < 2,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <I18nProvider locale={locale}>
        <TooltipProvider delayDuration={250}>
          <ToastProvider>{children}</ToastProvider>
        </TooltipProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}
