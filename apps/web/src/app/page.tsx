import { redirect } from "next/navigation";

import { BASE_PATH, DEMO } from "@/lib/demo/config";

export default function Home() {
  // The static demo has no server: an immediate meta refresh (works without JavaScript).
  if (DEMO) return <meta httpEquiv="refresh" content={`0;url=${BASE_PATH}/rfqs/`} />;
  redirect("/rfqs");
}
