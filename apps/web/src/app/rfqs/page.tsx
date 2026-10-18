import type { Metadata } from "next";

import { RfqsPage } from "@/components/pages/rfqs";

export const metadata: Metadata = { title: "Inbound RFQs" };

export default function Page() {
  return <RfqsPage />;
}
