import type { Metadata } from "next";

import { NotFound } from "@/components/not-found";

export const metadata: Metadata = { title: "Seite nicht gefunden" };

export default function NotFoundPage() {
  return <NotFound />;
}
