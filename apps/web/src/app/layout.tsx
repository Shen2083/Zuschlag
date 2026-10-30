import type { Metadata } from "next";
import { cookies, headers } from "next/headers";

import { AppSidebar } from "@/components/app-sidebar";
import { DemoBanner } from "@/components/demo-banner";
import { Providers } from "@/components/providers";
import { DEMO } from "@/lib/demo/config";
import type { Locale } from "@/lib/format";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Zuschlag.ai", template: "%s · Zuschlag.ai" },
  description: "Von der unstrukturierten Kundenanfrage zum SAP-konformen Angebot – mit KI.",
  openGraph: {
    type: "website",
    locale: "de_DE",
    siteName: "Zuschlag.ai",
    title: "Zuschlag.ai – Quote Studio",
    description:
      "Kundenanfrage rein, SAP-Angebot (ORDERS05) raus: KI-Stückliste, Materialabgleich mit MATMAS, Zuschlagskalkulation, GoBD-Freigabe.",
  },
  robots: { index: false, follow: false },
};

// Fonts come from the local system stack: no requests to third-party font CDNs.
export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  // The static demo has no request: German by default, switched in the browser.
  const locale: Locale = !DEMO && (await cookies()).get("locale")?.value === "en" ? "en" : "de";
  // Per-request CSP nonce (src/middleware.server.ts), for styles that libraries inject at runtime.
  const nonce = DEMO ? undefined : ((await headers()).get("x-nonce") ?? undefined);
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
          <div className="flex h-dvh flex-col overflow-hidden print:block print:h-auto print:overflow-visible">
            {DEMO && <DemoBanner />}
            <div className="flex min-h-0 flex-1 overflow-hidden print:block print:overflow-visible">
              <AppSidebar />
              <main
                id="main"
                className="flex min-w-0 flex-1 flex-col overflow-hidden print:overflow-visible"
              >
                {children}
              </main>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
