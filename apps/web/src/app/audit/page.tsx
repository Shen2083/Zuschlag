import type { Metadata } from "next";

import { AuditPage } from "@/components/pages/audit";

export const metadata: Metadata = { title: "GoBD Audit Log" };

export default function Page() {
  return <AuditPage />;
}
