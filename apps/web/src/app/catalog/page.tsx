import type { Metadata } from "next";

import { CatalogPage } from "@/components/pages/catalog";

export const metadata: Metadata = { title: "SAP Catalog" };

export default function Page() {
  return <CatalogPage />;
}
