"use client";

import { useEffect, useId, useState } from "react";
import type { QuoteDetail } from "@zuschlag/api-types";
import { CircleCheck, Loader2, TriangleAlert } from "lucide-react";

import { Input, Select } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { useI18n } from "@/i18n";
import { Dec } from "@/lib/decimal";
import {
  decimalForInput,
  formatMoney,
  formatPercent,
  parseDecimalInput,
  posex,
} from "@/lib/format";
import type { Totals, VatPercent } from "@/lib/pricing";
import { cn } from "@/lib/utils";

export const SLIDER_MAX = 50;
const STEP = Dec.from("0.5");

export interface TermsState {
  zterm: string;
  allowDeviation: boolean;
}

/**
 * The Zuschlag control: slider (0-50 %) and exact numeric input (0-100 %).
 * Every change recalculates line prices, VAT and totals locally at once; the
 * parent commits to the API after a short pause.
 */
export function ZuschlagControl({
  quote,
  totals,
  pct,
  vat,
  terms,
  locked,
  state,
  onChange,
  onTerms,
}: {
  quote: QuoteDetail;
  totals: Totals;
  pct: Dec;
  vat: VatPercent;
  terms: TermsState;
  locked: boolean;
  state: "idle" | "pending" | "error";
  onChange: (pct: Dec, vat: VatPercent) => void;
  onTerms: (terms: TermsState) => void;
}) {
  const { t, locale } = useI18n();
  const id = useId();
  const [text, setText] = useState(() => decimalForInput(pct, locale));
  const [focused, setFocused] = useState(false);
  const [invalid, setInvalid] = useState(false);
  useEffect(() => {
    if (!focused) setText(decimalForInput(pct, locale));
  }, [pct, locale, focused]);

  const set = (next: Dec) => {
    const clamped = next.isNegative() ? Dec.ZERO : next.cmp(100) > 0 ? Dec.from(100) : next;
    onChange(clamped, vat);
  };
  const money = (v: Dec) => formatMoney(v.toFixed(2), quote.currency, locale);
  const agreed = quote.customer?.agreed_payment_terms ?? [];

  return (
    <section aria-labelledby={`${id}-title`} className="border-t bg-card px-4 py-3">
      <div className="grid gap-x-8 gap-y-3 lg:grid-cols-[minmax(260px,1fr)_minmax(300px,380px)]">
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <h2
              id={`${id}-title`}
              className="text-xs font-semibold tracking-wide text-muted-foreground uppercase"
            >
              <label htmlFor={`${id}-pct`}>{t("studio.zuschlag")}</label>
            </h2>
            <div className="relative w-24">
              <Input
                id={`${id}-pct`}
                data-zuschlag-input
                inputMode="decimal"
                disabled={locked}
                value={text}
                aria-invalid={invalid || undefined}
                aria-label={t("studio.zuschlagInput")}
                aria-keyshortcuts="Z"
                onFocus={(e) => {
                  setFocused(true);
                  e.currentTarget.select();
                }}
                onBlur={() => {
                  setFocused(false);
                  setInvalid(false);
                  setText(decimalForInput(pct, locale));
                }}
                onChange={(e) => {
                  setText(e.target.value);
                  const parsed = parseDecimalInput(e.target.value, locale);
                  const ok =
                    parsed !== null &&
                    !Dec.from(parsed).isNegative() &&
                    Dec.from(parsed).cmp(100) <= 0;
                  setInvalid(!ok);
                  if (ok) set(Dec.from(parsed).quantize(2));
                }}
                onKeyDown={(e) => {
                  if (e.key === "ArrowUp" || e.key === "ArrowDown") {
                    e.preventDefault();
                    const step = e.shiftKey ? Dec.from(5) : STEP;
                    const next = e.key === "ArrowUp" ? pct.add(step) : pct.sub(step);
                    set(next);
                    setText(decimalForInput(next.isNegative() ? Dec.ZERO : next, locale));
                  } else if (e.key === "Enter" || e.key === "Escape") {
                    e.currentTarget.blur();
                  }
                }}
                className="h-9 pr-7 text-right text-base font-semibold tabular-nums"
              />
              <span className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 text-muted-foreground">
                %
              </span>
            </div>
            <Slider
              className="flex-1"
              min={0}
              max={SLIDER_MAX}
              step={0.5}
              disabled={locked}
              value={[Math.min(pct.toNumber(), SLIDER_MAX)]}
              onValueChange={([v]) => v !== undefined && set(Dec.from(v))}
              thumbLabel={t("studio.zuschlag")}
              valueText={formatPercent(pct, locale)}
            />
            <span
              className="w-14 text-right text-xs text-muted-foreground tabular-nums"
              aria-hidden
            >
              0–{SLIDER_MAX} %
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
            <fieldset className="flex items-center gap-2" disabled={locked}>
              <legend className="sr-only">{t("studio.vat")}</legend>
              <span className="text-muted-foreground" aria-hidden>
                {t("studio.vat")}
              </span>
              <div className="flex rounded-md border p-0.5">
                {([19, 7] as const).map((rate) => (
                  <label
                    key={rate}
                    className={cn(
                      "cursor-pointer rounded px-2 py-0.5 tabular-nums has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
                      vat === rate ? "bg-foreground text-background" : "hover:bg-secondary",
                    )}
                  >
                    <input
                      type="radio"
                      name={`${id}-vat`}
                      className="sr-only"
                      checked={vat === rate}
                      onChange={() => onChange(pct, rate)}
                    />
                    {rate} %
                  </label>
                ))}
              </div>
            </fieldset>

            <label className="flex items-center gap-2">
              <span className="text-muted-foreground">{t("studio.paymentTerms")}</span>
              {agreed.length > 0 && !terms.allowDeviation ? (
                <Select
                  value={terms.zterm}
                  disabled={locked}
                  onChange={(e) => onTerms({ ...terms, zterm: e.target.value })}
                  className="h-7 font-mono text-xs"
                >
                  {agreed.map((z) => (
                    <option key={z} value={z}>
                      {z}
                    </option>
                  ))}
                </Select>
              ) : (
                <Input
                  value={terms.zterm}
                  disabled={locked}
                  maxLength={4}
                  placeholder="NT30"
                  onChange={(e) => onTerms({ ...terms, zterm: e.target.value.toUpperCase() })}
                  className="h-7 w-20 font-mono text-xs"
                />
              )}
            </label>
            {agreed.length > 0 && (
              <label className="flex items-center gap-1.5 text-muted-foreground">
                <input
                  type="checkbox"
                  disabled={locked}
                  checked={terms.allowDeviation}
                  onChange={(e) =>
                    onTerms({
                      zterm: e.target.checked ? terms.zterm : (agreed[0] ?? ""),
                      allowDeviation: e.target.checked,
                    })
                  }
                  className="accent-[var(--primary)]"
                />
                {t("studio.allowDeviation")}
                <span className="font-mono whitespace-nowrap">
                  ({t("studio.agreed", { terms: agreed.join(", ") })})
                </span>
              </label>
            )}
          </div>

          <p
            role="status"
            aria-live="polite"
            className="flex items-center gap-1.5 text-xs text-muted-foreground"
          >
            {state === "pending" ? (
              <>
                <Loader2 className="size-3.5 animate-spin" aria-hidden />
                {t("studio.calculating")}
              </>
            ) : quote.calculated_at ? (
              <>
                <CircleCheck className="size-3.5 text-success" aria-hidden />
                {t("studio.calculated")}
              </>
            ) : (
              <>
                <TriangleAlert className="size-3.5 text-warning-foreground" aria-hidden />
                {t("studio.notCalculated")}
              </>
            )}
            {totals.missingPricePositions.length > 0 && (
              <span className="ml-2 text-warning-foreground">
                {t("studio.unpriced", {
                  positions: totals.missingPricePositions.map(posex).join(", "),
                })}
              </span>
            )}
          </p>
        </div>

        <dl
          className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-0.5 text-[12.5px] tabular-nums"
          aria-label={t("studio.net")}
        >
          <dt className="text-muted-foreground">{t("studio.materialCost")}</dt>
          <dd className="text-right">{money(totals.materialCost)}</dd>
          <dt className="text-muted-foreground">{t("studio.laborCost")}</dt>
          <dd className="text-right">{money(totals.laborCost)}</dd>
          <dt className="border-t pt-0.5">{t("studio.factoryCost")}</dt>
          <dd className="border-t pt-0.5 text-right">{money(totals.factoryCost)}</dd>
          <dt className="text-muted-foreground">
            + {t("studio.zuschlagAmount")} {formatPercent(totals.zuschlagPct, locale)}
          </dt>
          <dd className="text-right">{money(totals.zuschlagAmount)}</dd>
          <dt className="border-t pt-0.5 font-semibold">{t("studio.net")}</dt>
          <dd className="border-t pt-0.5 text-right font-semibold">{money(totals.netAmount)}</dd>
          <dt className="text-muted-foreground">
            + {t("studio.vatAmount", { rate: totals.vatRate })}
          </dt>
          <dd className="text-right">{money(totals.vatAmount)}</dd>
          <dt className="border-t-2 border-foreground pt-1 text-sm font-bold">
            {t("studio.gross")}
          </dt>
          <dd
            className="border-t-2 border-foreground pt-1 text-right text-sm font-bold"
            data-testid="gross-total"
          >
            {money(totals.grossAmount)}
          </dd>
        </dl>
      </div>
    </section>
  );
}
