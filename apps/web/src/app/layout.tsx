import type { Metadata } from "next";
import { cookies, headers } from "next/headers";

import { AppSidebar } from "@/components/app-sidebar";
import { Providers } from "@/components/providers";
import type { Locale } from "@/lib/format";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Zuschlag.ai", template: "%s · Zuschlag.ai" },
  description: "From unstructured RFQs to SAP-compliant quotes.",
  robots: { index: false, follow: false },
};

// Fonts come from the local system stack: no requests to third-party font CDNs.
export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const locale: Locale = (await cookies()).get("locale")?.value === "en" ? "en" : "de";
  // Per-request CSP nonce (src/middleware.ts), for styles that libraries inject at runtime.
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html lang={locale}>
      <body className="font-sans text-[13px]">
        <Providers locale={locale} nonce={nonce}>
          <a
            href="#main"
            className="sr-only z-50 rounded bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
          >
            {locale === "de" ? "Zum Inhalt springen" : "Skip to content"}
          </a>
          <div className="flex h-dvh overflow-hidden print:block print:h-auto print:overflow-visible">
            <AppSidebar />
            <main
              id="main"
              className="flex min-w-0 flex-1 flex-col overflow-hidden print:overflow-visible"
            >
              {children}
            </main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
