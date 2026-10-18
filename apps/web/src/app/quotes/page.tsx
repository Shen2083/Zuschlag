import type { Metadata } from "next";

import { QuotesPage } from "@/components/pages/quotes";

export const metadata: Metadata = { title: "Quote Studio" };

export default function Page() {
  return <QuotesPage />;
}
