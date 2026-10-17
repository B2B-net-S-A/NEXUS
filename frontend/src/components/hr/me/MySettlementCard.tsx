"use client";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Card } from "@/components/ui/card";
import type { MySettlement, PayrollLine, SettlementMonth } from "@/lib/api/hr-payroll";
import type { ViewState } from "@/lib/view-state";

import { capitalize, formatHours, formatMoney } from "../payroll/payroll-format";

const HOURS_SOURCE: Record<SettlementMonth["hours_source"], string> = {
  frozen: "zamknięty",
  approved: "szacunek · godziny zaakceptowane",
  entered: "szacunek · godziny wpisane",
  none: "szacunek · bez godzin",
};

/** „168 h × 95,00 zł = 15 960,00 zł · premie 1 500,00 zł” — jedna linia waluty. */
export function settlementLineText(month: Pick<SettlementMonth, "hours" | "rate_missing">, line: PayrollLine): string {
  const parts: string[] = [];
  if (line.hourly_rate != null && line.hours_amount != null) {
    parts.push(
      `${formatHours(month.hours)} h × ${formatMoney(line.hourly_rate, line.currency)} = ${formatMoney(
        line.hours_amount,
        line.currency,
      )}`,
    );
  } else if (month.rate_missing) {
    parts.push(`${formatHours(month.hours)} h · stawka nie ustawiona`);
  }
  if (Number(line.bonus_total) > 0) {
    parts.push(`premie ${formatMoney(line.bonus_total, line.currency)}`);
  }
  return parts.join(" · ") || "bez godzin i premii";
}

interface MySettlementCardProps {
  state: ViewState;
  data: MySettlement | undefined;
  onRetry: () => void;
}

/**
 * „Moje rozliczenie” (D3): zamknięte miesiące z linii zamrożonych przez Płace,
 * bieżący jako szacunek z „Mojego miesiąca”. Awaria to komunikat, nie zera.
 */
export function MySettlementCard({ state, data, onRetry }: MySettlementCardProps) {
  return (
    <Card size="sm" className="space-y-2" aria-labelledby="my-settlement-title">
      <h2
        id="my-settlement-title"
        className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground"
      >
        Moje rozliczenie
      </h2>
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Liczę rozliczenie…</p>
      ) : state !== "ready" && state !== "empty" ? (
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          description={
            state === "forbidden"
              ? "Rozliczenie widzą osoby z kartoteką pracownika."
              : "Nie udało się policzyć rozliczenia."
          }
          onRetry={onRetry}
        />
      ) : !data || data.months.length === 0 ? (
        <p className="text-sm text-muted-foreground">W tym roku nie ma jeszcze miesięcy do rozliczenia.</p>
      ) : (
        <ul className="divide-y divide-border/60">
          {data.months.map((month) => (
            <li
              key={`${month.year}-${month.month}`}
              className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 py-1.5"
            >
              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground">
                  {capitalize(month.label)}
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    {HOURS_SOURCE[month.hours_source]}
                  </span>
                </p>
                {month.lines.map((line) => (
                  <p key={line.currency} className="text-xs text-muted-foreground">
                    {settlementLineText(month, line)}
                  </p>
                ))}
              </div>
              <p className="text-sm font-semibold tabular-nums text-foreground">
                {month.lines.length === 0
                  ? "—"
                  : month.lines
                      .map((line) => `${month.final ? "" : "~ "}${formatMoney(line.total, line.currency)}`)
                      .join(" · ")}
              </p>
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-muted-foreground">
        Zamknięty miesiąc to linie zamrożone przez Płace. Bieżący liczymy z godzin w „Moim
        miesiącu” (wpisanych albo zaakceptowanych) i bieżącej stawki — zmienia się do zamknięcia,
        a Płace biorą tylko godziny zaakceptowane.
      </p>
    </Card>
  );
}
