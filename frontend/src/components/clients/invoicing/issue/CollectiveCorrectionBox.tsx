"use client";

import type { CollectiveCorrection } from "@/lib/api/issued-invoices";
import { formatIsoDatePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";

/**
 * Korekta zbiorcza rabatu od obrotu na karcie (22.11.2026): okres opustu, typ
 * korekty i faktury z KSeF, które wskazuje XML (`DaneFaKorygowanej`).
 */
export function CollectiveCorrectionBox({
  collective,
  currency,
}: {
  collective: CollectiveCorrection;
  currency: string;
}) {
  return (
    <section className="rounded-lg border border-border bg-card px-4 py-3 text-sm" aria-label="Korekta zbiorcza">
      <h3 className="mb-2 text-sm font-semibold text-foreground">Korekta zbiorcza rabatu</h3>
      <dl className="space-y-1 text-muted-foreground">
        <div className="flex justify-between gap-2">
          <dt>Okres opustu</dt>
          <dd className="tabular-nums">{collective.period.replace("-", " – ")}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt>Różnica stawek</dt>
          <dd className="tabular-nums">{collective.rate_diff.replace(".", ",")}%</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt>Nadwyżka ponad próg</dt>
          <dd className="tabular-nums">{formatMoney(collective.excess, collective.threshold_currency)}</dd>
        </div>
      </dl>
      <p className="mt-2 text-xs text-muted-foreground">
        Art. 106j ust. 3: jedna korekta na wszystkie faktury miesiąca w {currency}
        {collective.correction_type === "2" ? ", skutek w dacie korekty" : ""}.
      </p>
      <details className="mt-2">
        <summary className="cursor-pointer text-xs font-medium text-foreground">
          Faktury korygowane: {collective.invoice_count}
        </summary>
        <ul className="mt-1 max-h-[40dvh] space-y-1 overflow-y-auto text-xs">
          {collective.invoices.map((invoice) => (
            <li key={`${invoice.number}-${invoice.ksef_number ?? ""}`} className="border-b border-border/60 pb-1">
              <span className="block text-foreground">
                {invoice.number} · {formatIsoDatePl(invoice.issue_date)}
              </span>
              <span className="block break-all text-muted-foreground">{invoice.ksef_number ?? "poza KSeF"}</span>
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}
