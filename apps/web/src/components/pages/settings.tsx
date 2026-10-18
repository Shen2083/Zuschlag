"use client";

import { useState } from "react";
import type { TenantSettings } from "@zuschlag/api-types";
import { Loader2, Save } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { useI18n, useSetLocale } from "@/i18n";
import { useSaveSapProfile, useTenant } from "@/lib/api/queries";
import { formatMoney, formatPercent, type Locale } from "@/lib/format";
import { cn } from "@/lib/utils";

type Profile = NonNullable<TenantSettings["sap_outbound_profile"]>;
const FIELDS = [
  "mandt",
  "docrel",
  "sender_port",
  "sender_partner",
  "receiver_port",
  "receiver_partner",
  "vendor_number",
  "vendor_name",
] as const;

export function SettingsPage() {
  const { t, locale } = useI18n();
  const setLocale = useSetLocale();
  const { data, error } = useTenant();

  return (
    <>
      <PageHeader title={t("settings.title")} />
      <div className="min-h-0 flex-1 overflow-auto p-4">
        <div className="grid max-w-5xl gap-4 lg:grid-cols-2">
          <Panel title={t("settings.language")}>
            <div
              role="radiogroup"
              aria-label={t("settings.language")}
              className="flex w-fit rounded-md border p-0.5"
            >
              {(["de", "en"] as Locale[]).map((l) => (
                <button
                  key={l}
                  role="radio"
                  aria-checked={locale === l}
                  onClick={() => setLocale(l)}
                  className={cn(
                    "rounded px-3 py-1 text-xs",
                    locale === l ? "bg-foreground text-background" : "hover:bg-secondary",
                  )}
                >
                  {l === "de" ? "Deutsch (de-DE)" : "English"}
                </button>
              ))}
            </div>
          </Panel>

          {error && (
            <p role="alert" className="text-destructive">
              {error.message}
            </p>
          )}
          {data && (
            <>
              <Panel title={t("settings.tenant")}>
                <Rows
                  rows={[
                    [t("settings.tenant"), data.name],
                    [t("settings.region"), data.data_region],
                    [
                      "SAP",
                      `${data.sap_client ?? "—"} / ${data.sap_sales_org ?? "—"} · ${data.sap_outbound_transport}`,
                    ],
                  ]}
                />
              </Panel>
              <ProfileForm initial={data.sap_outbound_profile} />
              <Panel title={t("settings.quoting")}>
                <Rows
                  rows={[
                    [t("studio.zuschlag"), formatPercent(data.quoting.zuschlag_pct, locale)],
                    [t("studio.vat"), formatPercent(data.quoting.vat_rate, locale)],
                    [t("studio.paymentTerms"), data.quoting.payment_terms],
                    [
                      t("settings.threshold"),
                      formatPercent(data.quoting.review_threshold * 100, locale),
                    ],
                    ...Object.entries(data.quoting.labor_rates_eur).map(
                      ([op, rate]) =>
                        [
                          `${t("settings.laborRates")} · ${op}`,
                          `${formatMoney(rate, "EUR", locale)}/h`,
                        ] as [string, string],
                    ),
                  ]}
                />
              </Panel>
              <Panel title={t("settings.ai")}>
                <Rows
                  rows={[
                    [
                      "LLM",
                      `${data.ai.llm_provider} · ${data.ai.llm_model} · ${data.ai.llm_region}`,
                    ],
                    [
                      t("settings.zdr"),
                      data.ai.zero_data_retention_attested ? t("common.yes") : t("common.no"),
                    ],
                    ["Embeddings", `${data.ai.embedding_provider} · ${data.ai.embedding_model}`],
                  ]}
                />
              </Panel>
            </>
          )}
        </div>
      </div>
    </>
  );
}

function ProfileForm({ initial }: { initial: Profile | null }) {
  const { t } = useI18n();
  const toast = useToast();
  const save = useSaveSapProfile();
  const [form, setForm] = useState<Record<(typeof FIELDS)[number], string>>(
    () =>
      Object.fromEntries(FIELDS.map((f) => [f, initial?.[f] ?? ""])) as Record<
        (typeof FIELDS)[number],
        string
      >,
  );

  return (
    <Panel title={t("settings.profile")} className="lg:row-span-2">
      <p className="mb-3 text-xs text-muted-foreground">{t("settings.profileHelp")}</p>
      <form
        className="grid grid-cols-2 gap-x-3 gap-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate({ ...(initial ?? {}), ...form } as Profile, {
            onSuccess: () => toast({ kind: "success", title: t("settings.saved") }),
            onError: (err) =>
              toast({ kind: "error", title: t("common.error"), detail: err.message }),
          });
        }}
      >
        {FIELDS.map((f) => (
          <label
            key={f}
            className={cn("flex flex-col gap-1 text-xs", f === "vendor_name" && "col-span-2")}
          >
            <span className="text-muted-foreground">{t(`settings.fields.${f}`)}</span>
            <Input
              required
              value={form[f]}
              onChange={(e) => setForm({ ...form, [f]: e.target.value })}
              className="font-mono"
            />
          </label>
        ))}
        <Button type="submit" size="sm" className="col-span-2 mt-2 w-fit" disabled={save.isPending}>
          {save.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Save aria-hidden />}
          {t("common.save")}
        </Button>
      </form>
    </Panel>
  );
}

function Panel({
  title,
  children,
  className,
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-lg border bg-card p-4", className)} aria-label={title}>
      <h2 className="mb-3 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Rows({ rows }: { rows: Array<[string, string]> }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="font-mono text-xs">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
