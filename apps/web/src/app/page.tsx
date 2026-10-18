import { Database, Inbox, Lock, MapPin, ShieldCheck, Sparkles } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getApiHealth } from "@/lib/api";

export const dynamic = "force-dynamic";

const KPIS = [
  { label: "Open RFQs", value: "0", hint: "awaiting parsing" },
  { label: "Draft quotes", value: "0", hint: "awaiting approval" },
  { label: "Median turnaround", value: "—", hint: "RFQ → quote" },
  { label: "SAP match rate", value: "—", hint: "auto-matched lines" },
];

export default async function DashboardPage() {
  const health = await getApiHealth();

  return (
    <>
      <PageHeader title="Dashboard">
        <Badge variant="outline">
          <MapPin aria-hidden />
          {health ? `EU · ${health.region}` : "EU"}
        </Badge>
        {health?.llm.zdr_attested && (
          <Badge variant="outline">
            <Lock aria-hidden />
            Zero data retention
          </Badge>
        )}
      </PageHeader>

      <div className="space-y-6 p-6">
        <section aria-label="Key figures" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {KPIS.map((kpi) => (
            <Card key={kpi.label} className="gap-1 py-4">
              <CardContent className="px-4">
                <p className="text-xs text-muted-foreground">{kpi.label}</p>
                <p className="mt-1 text-2xl font-semibold tracking-tight">{kpi.value}</p>
                <p className="text-xs text-muted-foreground">{kpi.hint}</p>
              </CardContent>
            </Card>
          ))}
        </section>

        <div className="grid gap-6 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Inbound requests</CardTitle>
              <CardDescription>
                Unstructured RFQs (e-mail, PDF, spec sheets) land here for AI parsing.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-12 text-center">
                <Inbox className="mb-3 size-8 text-muted-foreground" aria-hidden />
                <p className="text-sm font-medium">No requests yet</p>
                <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                  Connect a shared mailbox or upload a spec sheet to generate your first bill of
                  materials.
                </p>
                <Button className="mt-4" disabled>
                  <Sparkles aria-hidden />
                  Generate quote with AI
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Platform status</CardTitle>
              <CardDescription>Compliance baseline of this deployment</CardDescription>
            </CardHeader>
            <CardContent>
              <dl className="space-y-3 text-sm">
                <StatusRow icon={<Database aria-hidden />} label="API">
                  {health ? (
                    <Badge variant="success">online · {health.environment}</Badge>
                  ) : (
                    <Badge variant="destructive">unreachable</Badge>
                  )}
                </StatusRow>
                <StatusRow icon={<MapPin aria-hidden />} label="Data residency">
                  <span className="font-mono text-xs">
                    {health ? `${health.cloud_provider} · ${health.region}` : "—"}
                  </span>
                </StatusRow>
                <StatusRow icon={<ShieldCheck aria-hidden />} label="LLM retention">
                  {health?.llm.zdr_attested ? (
                    <Badge variant="success">ZDR attested</Badge>
                  ) : (
                    <Badge variant="secondary">LLM disabled</Badge>
                  )}
                </StatusRow>
              </dl>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}

function StatusRow({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="flex items-center gap-2 text-muted-foreground [&_svg]:size-4">
        {icon}
        {label}
      </dt>
      <dd>{children}</dd>
    </div>
  );
}
