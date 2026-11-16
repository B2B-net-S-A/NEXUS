import type { InvoiceRebate } from "@/lib/api/issued-invoices";
import { monthTitlePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";

function percent(rate: string): string {
  return `${rate.replace(".", ",")}%`;
}

/** „do 15 000 000,00 EUR 2,5%, nadwyżka 3%” — progi z ustawień klienta. */
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
 * Rabat od obrotu rocznego na karcie faktury (decyzje Artura 16.11.2026): pozycja
 * „Rabat od obrotu” po stawce progu z obrotu do końca poprzedniego miesiąca,
 * licznik do progu dla Finansów i korekta za miesiąc przekroczenia (różnica
 * stawek od części obrotu ponad próg).
 */
export function InvoiceRebateBox({ rebate }: { rebate: InvoiceRebate }) {
  const thr = rebate.threshold_currency;
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
            {rebate.on_invoice !== null ? `−${formatMoney(rebate.on_invoice, rebate.currency)}` : "brak pozycji"}
          </dd>
        </div>
      </dl>
      {rebate.on_invoice === null ? (
        <p className="mt-1 text-xs text-destructive">
          Faktura nie ma pozycji „Rabat od obrotu” — klient ma rabat z umowy ramowej.
        </p>
      ) : null}
      {rebate.corrections.map((correction) => (
        <p key={correction.month} className="mt-2 rounded-md bg-muted/50 px-2 py-1 text-xs text-foreground">
          Korekta za {monthTitlePl({ year: rebate.year, month: correction.month })}:{" "}
          {percent(correction.rate_diff)} od {formatMoney(correction.excess, thr)} ponad próg ={" "}
          {correction.amounts.map((a) => formatMoney(a.amount, a.currency)).join(" + ")}. Do KSeF po zgodzie.
        </p>
      ))}
      <p className="mt-2 text-xs text-muted-foreground">
        Progi: {rebateTiersText(rebate)}. Stawka z obrotu do końca poprzedniego miesiąca; wyższa stawka tylko od
        nadwyżki ponad próg.
      </p>
      {rebate.excluded > 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">
          Poza obrotem pozycje podróży i refaktur z {rebate.excluded} fakt.
        </p>
      ) : null}
      {rebate.missing_fx > 0 ? (
        <p className="mt-1 text-xs text-destructive">
          Bez kursu NBP do progu: {rebate.missing_fx} fakt. — obrót może być zaniżony.
        </p>
      ) : null}
    </section>
  );
}
