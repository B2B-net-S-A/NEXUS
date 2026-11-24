"use client";

import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { InvoiceRebate, RebateCorrectionQuery } from "@/lib/api/issued-invoices";
import { monthTitlePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";

import { RebateCorrectionDialog } from "./RebateCorrectionDialog";

function percent(rate: string): string {
  return `${rate.replace(".", ",")}%`;
}

/** Np. „do 1 000 000,00 EUR 1%, nadwyżka 2%” (liczby fikcyjne) — progi z ustawień klienta. */
export function rebateTiersText(rebate: InvoiceRebate): string {
  return rebate.tiers
    .map((tier, index) => {
      if (tier.up_to !== null) {
        return `do ${formatMoney(tier.up_to, rebate.threshold_currency)} ${percent(tier.rate)}`;
      }
      return index === 0 ? percent(tier.rate) : `nadwyżka ${percent(tier.rate)}`;
    })
    .join(", ");
}

/**
 * Rabat od obrotu rocznego na karcie faktury (decyzje Artura 16.11.2026): rabat %
 * na wierszach (jak w eBI24) po stawce progu z obrotu przed rabatem do końca
 * poprzedniego miesiąca,
 * licznik do progu dla Finansów i korekta za miesiąc przekroczenia (różnica
 * stawek od części obrotu ponad próg).
 */
export function InvoiceRebateBox({
  rebate,
  clientId = null,
}: {
  rebate: InvoiceRebate;
  clientId?: number | null;
}) {
  const thr = rebate.threshold_currency;
  const [draft, setDraft] = useState<RebateCorrectionQuery | null>(null);
  return (
    <section className="rounded-lg border border-border bg-card px-4 py-3 text-sm" aria-label="Rabat od obrotu">
      <h3 className="mb-2 text-sm font-semibold text-foreground">
        Rabat od obrotu {rebate.year} · {percent(rebate.rate)}
      </h3>
      <dl className="space-y-1">
        <div className="flex justify-between gap-2 text-muted-foreground">
          <dt>Obrót do końca poprz. miesiąca</dt>
          <dd className="tabular-nums">{formatMoney(rebate.turnover_before, thr)}</dd>
        </div>
        <div className="flex justify-between gap-2 text-muted-foreground">
          <dt>Obrót z tą fakturą</dt>
          <dd className="tabular-nums">{formatMoney(rebate.turnover, thr)}</dd>
        </div>
        {rebate.next_rate && rebate.to_next !== null ? (
          <div className="flex justify-between gap-2 text-muted-foreground">
            <dt>Do progu {percent(rebate.next_rate)}</dt>
            <dd className="tabular-nums">{formatMoney(rebate.to_next, thr)}</dd>
          </div>
        ) : null}
        <div className="flex justify-between gap-2 border-t border-border pt-1 font-semibold text-foreground">
          <dt>Rabat na tej fakturze</dt>
          <dd className="tabular-nums">
            {rebate.on_invoice !== null ? `−${formatMoney(rebate.on_invoice, rebate.currency)}` : "brak rabatu"}
          </dd>
        </div>
      </dl>
      {rebate.on_invoice === null ? (
        <p className="mt-1 text-xs text-destructive">
          Żaden wiersz nie ma rabatu % — klient ma rabat od obrotu z umowy ramowej.
        </p>
      ) : null}
      {rebate.corrections.map((correction) => {
        const label = monthTitlePl({ year: rebate.year, month: correction.month });
        return (
          <div key={correction.month} className="mt-2 rounded-md bg-muted/50 px-2 py-1 text-xs text-foreground">
            <p>
              Korekta za {label}: {percent(correction.rate_diff)} od {formatMoney(correction.excess, thr)} ponad
              próg = {correction.amounts.map((a) => formatMoney(a.amount, a.currency)).join(" + ")}. Do KSeF po
              zgodzie.
            </p>
            {(correction.issued ?? []).map((ref) => (
              <Link
                key={ref.id}
                href={`/finance/faktury/${ref.id}`}
                className="mt-1 block text-primary underline-offset-2 hover:underline"
              >
                {ref.invoice_number
                  ? `Korekta ${ref.invoice_number} (${ref.status_label.toLowerCase()})`
                  : "Korekta — szkic bez numeru"}
                {correction.amounts.length > 1 ? `, ${ref.currency}` : ""}
              </Link>
            ))}
            {clientId
              ? correction.amounts
                  .filter((a) => !(correction.issued ?? []).some((ref) => ref.currency === a.currency))
                  .map((a) => (
                  <Button
                    key={a.currency}
                    size="sm"
                    variant="outline"
                    className="mt-1 h-auto w-full justify-start whitespace-normal py-1 text-left"
                    onClick={() =>
                      setDraft({ clientId, year: rebate.year, month: correction.month, currency: a.currency })
                    }
                  >
                    Szkic korekty rabatu za {label.toLowerCase()}
                    {correction.amounts.length > 1 ? ` (${a.currency})` : ""}
                  </Button>
                ))
              : null}
          </div>
        );
      })}
      {draft ? <RebateCorrectionDialog query={draft} onClose={() => setDraft(null)} /> : null}
      <p className="mt-2 text-xs text-muted-foreground">
        Progi: {rebateTiersText(rebate)}. Obrót przed rabatem; stawka z obrotu do końca poprzedniego miesiąca;
        wyższa stawka tylko od nadwyżki ponad próg.
      </p>
      {rebate.excluded > 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">
          Poza obrotem pozycje podróży i refaktur z {rebate.excluded} fakt.
        </p>
      ) : null}
      {rebate.archived > 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">
          W obrocie {rebate.archived} fakt. sprzed KSeF z archiwum eBI24.
        </p>
      ) : null}
      {rebate.missing_fx > 0 ? (
        <p className="mt-1 text-xs text-destructive">
          Bez kursu NBP do progu: {rebate.missing_fx} fakt. — obrót może być zaniżony.
        </p>
      ) : null}
      {rebate.unreadable > 0 ? (
        <p className="mt-1 text-xs text-destructive">
          Bez czytelnego pliku w archiwum eBI24: {rebate.unreadable} fakt. — obrót może być zaniżony.
        </p>
      ) : null}
    </section>
  );
}
