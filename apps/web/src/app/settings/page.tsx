import type { Metadata } from "next";

import { SettingsPage } from "@/components/pages/settings";

export const metadata: Metadata = { title: "Einstellungen" };

export default function Page() {
  return <SettingsPage />;
}
