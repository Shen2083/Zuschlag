import type { Metadata } from "next";

import { AppSidebar } from "@/components/app-sidebar";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Zuschlag.ai", template: "%s · Zuschlag.ai" },
  description: "From unstructured RFQs to SAP-compliant quotes.",
  robots: { index: false, follow: false },
};

// Fonts come from the local system stack: no requests to third-party font CDNs.
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="de">
      <body className="font-sans">
        <div className="flex min-h-dvh">
          <AppSidebar />
          <main className="flex min-w-0 flex-1 flex-col">{children}</main>
        </div>
      </body>
    </html>
  );
}
