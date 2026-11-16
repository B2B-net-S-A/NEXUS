import type { InvoiceRebate } from "@/lib/api/issued-invoices";
import { formatIsoDatePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";

function percent(rate: string): string {
  return `${rate.replace(".", ",")}%`;
}

/** „do 15 000 000,00 EUR 2,5%, powyżej 3%” — progi z ustawień klienta. */
export function rebateTiersText(rebate: InvoiceRebate): string {
  return rebate.tiers
    .map((tier, index) => {
      if (tier.up_to !== null) {
        return `do ${formatMoney(tier.up_to, rebate.threshold_currency)} ${percent(tier.rate)}`;
      }
      return index === 0 ? percent(tier.rate) : `powyżej ${percent(tier.rate)}`;
    })
    .join(", ");
}

/**
 * Rabat roczny od obrotu na karcie faktury (decyzje Artura 16.11.2026): stan
 * roku razem z tą fakturą, stawka progu od całego obrotu i udział tej faktury.
 * Informacja, nie pozycja faktury — rozlicza go zbiorcza korekta do 31.01.
 */
export function InvoiceRebateBox({ rebate }: { rebate: InvoiceRebate }) {
  return (
    <section
      className="rounded-lg border border-border bg-card px-4 py-3 text-sm"
      aria-label="Rabat roczny"
    >
      <h3 className="mb-2 text-sm font-semibold text-foreground">
        Rabat roczny {rebate.year} · {percent(rebate.rate)}
      </h3>
      <dl className="space-y-1">
        <div className="flex justify-between gap-2 text-muted-foreground">
          <dt>Obrót roku</dt>
          <dd className="tabular-nums">{formatMoney(rebate.turnover, rebate.threshold_currency)}</dd>
        </div>
        {rebate.next_rate && rebate.to_next !== null ? (
          <div className="flex justify-between gap-2 text-muted-foreground">
            <dt>Do progu {percent(rebate.next_rate)}</dt>
            <dd className="tabular-nums">{formatMoney(rebate.to_next, rebate.threshold_currency)}</dd>
          </div>
        ) : null}
        {rebate.totals.map((total) => (
          <div key={total.currency} className="flex justify-between gap-2 text-foreground">
            <dt>{rebate.totals.length > 1 ? `Rabat w ${total.currency}` : "Rabat narastająco"}</dt>
            <dd className="tabular-nums">{formatMoney(total.rebate, total.currency)}</dd>
          </div>
        ))}
        {rebate.this_invoice !== null ? (
          <div className="flex justify-between gap-2 border-t border-border pt-1 font-semibold text-foreground">
            <dt>Z tej faktury</dt>
            <dd className="tabular-nums">{formatMoney(rebate.this_invoice, rebate.currency)}</dd>
          </div>
        ) : null}
      </dl>
      <p className="mt-2 text-xs text-muted-foreground">
        Progi: {rebateTiersText(rebate)} od całego obrotu roku. Rabat nie jest pozycją tej faktury —
        rozlicza go zbiorcza korekta do {formatIsoDatePl(rebate.settle_by)}.
      </p>
      {rebate.excluded > 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">
          Poza obrotem (podróże, refaktury): {rebate.excluded} fakt.
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
