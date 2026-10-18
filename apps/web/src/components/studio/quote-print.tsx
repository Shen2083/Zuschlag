"use client";

import { useEffect, useRef } from "react";
import { Loader2, Printer } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n";
import { useQuote, useTenant } from "@/lib/api/queries";
import { formatDate, formatMoney, formatNumber, formatPercent, posex } from "@/lib/format";

/**
 * Customer-facing quote as an A4 document. "Export PDF" opens this page and the
 * browser's print dialog ("Save as PDF"); the figures are the server's stored
 * calculation, not the live draft.
 */
export function QuotePrint({ id }: { id: string }) {
  const { t, locale } = useI18n();
  const { data: quote } = useQuote(id);
  const { data: tenant } = useTenant();
  const printed = useRef(false);

  useEffect(() => {
    if (quote && tenant && !printed.current) {
      printed.current = true;
      document.title = `${quote.quote_number} – ${quote.customer?.name1 ?? quote.customer_name ?? ""}`;
      setTimeout(() => window.print(), 300);
    }
  }, [quote, tenant]);

  if (!quote) {
    return (
      <p role="status" className="flex items-center gap-2 p-6 text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        {t("common.loading")}
      </p>
    );
  }

  const money = (v: string | null, places = 2) =>
    formatMoney(v, quote.currency, locale, { places, minPlaces: 2 });
  const vendor = tenant?.sap_outbound_profile?.vendor_name ?? tenant?.name ?? "";
  const c = quote.customer;
  const de = locale === "de";

  return (
    <div className="overflow-auto bg-secondary print:overflow-visible print:bg-white">
      <div className="sticky top-0 flex justify-end gap-2 border-b bg-card px-4 py-2 print:hidden">
        <Button size="sm" onClick={() => window.print()}>
          <Printer aria-hidden />
          {t("studio.exportPdf")}
        </Button>
      </div>
      <article className="mx-auto my-6 w-[210mm] min-h-[297mm] bg-white p-[16mm] text-[10.5pt] text-black shadow-lg print:my-0 print:w-auto print:min-h-0 print:p-0 print:shadow-none">
        <header className="flex justify-between border-b-2 border-black pb-4">
          <div>
            <p className="text-lg font-bold">{vendor}</p>
            {tenant?.sap_outbound_profile && (
              <p className="text-xs">
                {de ? "Lieferantennr." : "Vendor no."} {tenant.sap_outbound_profile.vendor_number}
              </p>
            )}
          </div>
          <div className="text-right">
            <p className="text-2xl font-bold tracking-tight">{de ? "Angebot" : "Quotation"}</p>
            <p className="font-mono">{quote.quote_number}</p>
          </div>
        </header>

        <section className="mt-6 flex justify-between gap-8">
          <address className="not-italic">
            <p className="font-semibold">{c?.name1 ?? quote.customer_name}</p>
            {c?.name2 && <p>{c.name2}</p>}
            {quote.contact_name && (
              <p>
                {de ? "z. Hd." : "Attn."} {quote.contact_name}
              </p>
            )}
            {c?.street && <p>{c.street}</p>}
            {(c?.postal_code || c?.city) && (
              <p>
                {c?.postal_code} {c?.city}
              </p>
            )}
            {c?.country && <p>{c.country}</p>}
          </address>
          <dl className="grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5 text-sm">
            <dt>{de ? "Datum" : "Date"}</dt>
            <dd>{formatDate(quote.calculated_at ?? quote.created_at, locale)}</dd>
            {c && (
              <>
                <dt>{de ? "Kundennr." : "Customer no."}</dt>
                <dd className="font-mono">{c.kunnr}</dd>
              </>
            )}
            {quote.rfq?.customer_ref && (
              <>
                <dt>{de ? "Ihre Anfrage" : "Your inquiry"}</dt>
                <dd>{quote.rfq.customer_ref}</dd>
              </>
            )}
            {quote.requested_delivery_date && (
              <>
                <dt>{de ? "Liefertermin" : "Delivery"}</dt>
                <dd>{formatDate(quote.requested_delivery_date, locale)}</dd>
              </>
            )}
          </dl>
        </section>

        <table className="mt-8 w-full border-collapse text-[9.5pt]">
          <thead>
            <tr className="border-b-2 border-black text-left">
              <th className="py-1 pr-2">{de ? "Pos." : "Item"}</th>
              <th className="py-1 pr-2">{de ? "Material" : "Material"}</th>
              <th className="py-1 pr-2">{de ? "Bezeichnung" : "Description"}</th>
              <th className="py-1 pr-2 text-right">{de ? "Menge" : "Qty"}</th>
              <th className="py-1 pr-2">{de ? "ME" : "Unit"}</th>
              <th className="py-1 pr-2 text-right">{de ? "Einzelpreis" : "Unit price"}</th>
              <th className="py-1 text-right">{de ? "Gesamt" : "Total"}</th>
            </tr>
          </thead>
          <tbody>
            {quote.items.map((item) => (
              <tr key={item.id} className="border-b border-black/20 align-top break-inside-avoid">
                <td className="py-1.5 pr-2 font-mono">{posex(item.position)}</td>
                <td className="py-1.5 pr-2 font-mono">{item.matnr ?? "—"}</td>
                <td className="py-1.5 pr-2">
                  {item.description}
                  {item.specs.length > 0 && (
                    <p className="text-[8.5pt] text-black/70">
                      {item.specs
                        .map((s) => `${s.name}: ${s.value}${s.unit ? ` ${s.unit}` : ""}`)
                        .join(" · ")}
                    </p>
                  )}
                </td>
                <td className="py-1.5 pr-2 text-right tabular-nums">
                  {formatNumber(item.quantity, locale)}
                </td>
                <td className="py-1.5 pr-2">{item.uom}</td>
                <td className="py-1.5 pr-2 text-right tabular-nums">{money(item.unit_price, 4)}</td>
                <td className="py-1.5 text-right tabular-nums">{money(item.line_total)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <dl className="mt-4 ml-auto grid w-72 grid-cols-[1fr_auto] gap-y-0.5 tabular-nums">
          <dt>{de ? "Nettobetrag" : "Net amount"}</dt>
          <dd className="text-right">{money(quote.net_total)}</dd>
          <dt>
            {de ? "zzgl. MwSt." : "plus VAT"} {formatPercent(quote.vat_rate ?? "19", locale)}
          </dt>
          <dd className="text-right">{money(quote.vat_amount)}</dd>
          <dt className="border-t-2 border-black pt-1 font-bold">
            {de ? "Gesamtbetrag" : "Total"}
          </dt>
          <dd className="border-t-2 border-black pt-1 text-right font-bold">
            {money(quote.gross_total)}
          </dd>
        </dl>

        <footer className="mt-10 space-y-1 text-[9pt]">
          {quote.payment_terms && (
            <p>
              {de ? "Zahlungsbedingung" : "Payment terms"}:{" "}
              <span className="font-mono">{quote.payment_terms}</span>
            </p>
          )}
          <p>
            {de ? "Preise in" : "Prices in"} {quote.currency}.
          </p>
          {quote.status !== "approved" && quote.status !== "synced" && (
            <p className="mt-4 border border-black p-2 font-semibold">
              {de ? "ENTWURF – noch nicht freigegeben" : "DRAFT – not yet approved"}
            </p>
          )}
        </footer>
      </article>
    </div>
  );
}
