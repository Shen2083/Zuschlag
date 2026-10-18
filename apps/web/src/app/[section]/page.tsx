import { notFound } from "next/navigation";
import { Construction } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { NAV_ITEMS } from "@/lib/nav";

export default async function SectionPage({ params }: { params: Promise<{ section: string }> }) {
  const { section } = await params;
  const item = NAV_ITEMS.find((n) => n.slug === section && n.slug !== "");
  if (!item) notFound();

  return (
    <>
      <PageHeader title={item.label} />
      <div className="flex flex-1 flex-col items-center justify-center p-12 text-center">
        <Construction className="mb-3 size-8 text-muted-foreground" aria-hidden />
        <p className="text-sm font-medium">{item.label} is not built yet</p>
      </div>
    </>
  );
}
