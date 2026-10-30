import type { Metadata } from "next";

import { CustomersPage } from "@/components/pages/customers";

export const metadata: Metadata = { title: "Kunden" };

export default function Page() {
  return <CustomersPage />;
}
