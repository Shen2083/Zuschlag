import type { Metadata } from "next";

import { DEMO } from "@/lib/demo/config";
import { demoQuoteIds } from "@/lib/demo/ids";

import { QuotePrint } from "@/components/studio/quote-print";

export const metadata: Metadata = { title: "Angebot drucken" };

/** Static demo: every quote page it can show is generated at build time. */
export function generateStaticParams() {
  return DEMO ? demoQuoteIds().map((id) => ({ id })) : [];
}

export default async function QuotePrintPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <QuotePrint id={id} />;
}
