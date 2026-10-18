import type { Metadata } from "next";

import { QuotePrint } from "@/components/studio/quote-print";

export const metadata: Metadata = { title: "Angebot drucken" };

export default async function QuotePrintPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <QuotePrint id={id} />;
}
