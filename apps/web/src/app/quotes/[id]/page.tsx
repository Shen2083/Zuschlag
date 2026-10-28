import type { Metadata } from "next";

import { DEMO } from "@/lib/demo/config";
import { demoQuoteIds } from "@/lib/demo/ids";

import { QuoteStudio } from "@/components/studio/quote-studio";

export const metadata: Metadata = { title: "Quote Studio" };

/** Static demo: every quote page it can show is generated at build time. */
export function generateStaticParams() {
  return DEMO ? demoQuoteIds().map((id) => ({ id })) : [];
}

export default async function QuoteStudioPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <QuoteStudio id={id} />;
}
