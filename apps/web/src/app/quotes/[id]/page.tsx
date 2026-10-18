import type { Metadata } from "next";

import { QuoteStudio } from "@/components/studio/quote-studio";

export const metadata: Metadata = { title: "Quote Studio" };

export default async function QuoteStudioPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <QuoteStudio id={id} />;
}
