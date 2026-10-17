"use client";

import { InlineStats, type InlineStat } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useMyPayroll, useMySettlement, type MyPayroll, type MySettlement } from "@/lib/api/hr-payroll";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";
import { formatMoney } from "@/lib/money";
import { formatIsoDatePl } from "@/lib/date-pl";

import { BonusStagesTable } from "../me/BonusStagesTable";
import { MySettlementCard } from "../me/MySettlementCard";
import {
  assignedInYear,
  inTransitLabel,
  inTransitSummary,
  myBonusItems,
  totalsLabel,
} from "../me/overview-format";

/**
 * Liczby nad listą: moja stawka, premie w drodze (propozycje + prognozy
 * z podpisanych umów), przyznane w roku i — gdy rozliczenie się wczytało —
 * wypłacone w roku (premie z zamkniętych miesięcy).
 */
export function myStats(
  data: MyPayroll,
  today: string = warsawToday(),
  settlement?: MySettlement,
): InlineStat[] {
  const year = Number(today.slice(0, 4));
  const transit = inTransitSummary(myBonusItems(data, today));
  const stats: InlineStat[] = [
    {
      id: "rate",
      label: data.current_rate
        ? `moja stawka od ${formatIsoDatePl(data.current_rate.effective_from)}`
        : "moja stawka",
      value: data.current_rate
        ? `${formatMoney(data.current_rate.hourly_rate, data.current_rate.currency)}/h`
        : "nie ustawiona",
    },
  ];
  if (transit.count > 0) {
    stats.push({
      id: "waiting",
      label: `w drodze (${transit.count})`,
      value: inTransitLabel(transit),
      title:
        transit.unknown > 0
          ? `${transit.unknown} bez kwoty — kontrakt nie ma jeszcze stawki klienta.`
          : "Szacunek z reguł premii; kwotę zatwierdzają Płace.",
    });
  }
  stats.push({
    id: "bonuses",
    label: `premie przyznane w ${year}`,
    value: totalsLabel(assignedInYear(data.bonuses, year)),
  });
  if (settlement && settlement.year === year) {
    stats.push({
      id: "paid",
      label: `premie wypłacone w ${year}`,
      value: totalsLabel(settlement.bonuses_paid),
      title: "Premie z miesięcy zamkniętych w płacach.",
    });
  }
  return stats;
}

/**
 * „Mój czas → Premie i stawka”: moje premie z etapami (umowa → 21 dni →
 * decyzja Płac → wypłata), także „w drodze” od podpisania umowy i anulowane
 * z powodem; „Moje rozliczenie” i historia stawki. Tylko o sobie.
 */
export function MyBonusesTab() {
  const today = warsawToday();
  const year = Number(today.slice(0, 4));
  const me = useMyPayroll();
  const settlement = useMySettlement(year);
  const data = me.data;
  const items = data ? myBonusItems(data, today) : [];
  const state = resolveViewState({
    isLoading: me.isLoading,
    isError: me.isError,
    error: me.error,
    isSuccess: me.isSuccess,
    isEmpty: items.length === 0,
  });
  const settlementState = resolveViewState({
    isLoading: settlement.isLoading,
    isError: settlement.isError,
    error: settlement.error,
    isSuccess: settlement.isSuccess,
  });

  if (state === "loading") {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie premii…</p>;
  }
  if (state === "forbidden" || state === "not_found" || state === "error" || !data) {
    return (
      <QueryStateNotice
        state={state === "forbidden" || state === "not_found" ? state : "error"}
        description={
          state === "not_found"
            ? "Moduł Płac nie jest jeszcze włączony."
            : state === "forbidden"
              ? "Premie widzą osoby z kartoteką pracownika."
              : undefined
        }
        onRetry={() => me.refetch()}
      />
    );
  }

  return (
    <div className="space-y-3">
      <InlineStats
        id="my-bonuses-stats"
        stats={myStats(data, today, settlementState === "ready" ? settlement.data : undefined)}
      />
      {state === "empty" ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          Nie masz jeszcze premii. Premia z placementu pojawi się tu od podpisania umowy
          z konsultantem.
        </div>
      ) : (
        <BonusStagesTable items={items} />
      )}
      <MySettlementCard
        state={settlementState}
        data={settlement.data}
        onRetry={() => settlement.refetch()}
      />
      {data.rates.length > 0 ? (
        <section aria-labelledby="my-rate-history" className="space-y-1 text-sm">
          <h2
            id="my-rate-history"
            className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground"
          >
            Historia stawki
          </h2>
          <ul className="space-y-0.5 text-muted-foreground">
            {data.rates.map((rate) => (
              <li key={rate.id}>
                <span className="font-medium text-foreground">
                  {formatMoney(rate.hourly_rate, rate.currency)}/h
                </span>{" "}
                {rate.effective_to
                  ? `${formatIsoDatePl(rate.effective_from)} – ${formatIsoDatePl(rate.effective_to)}`
                  : `od ${formatIsoDatePl(rate.effective_from)}`}
                {rate.reason ? ` · ${rate.reason}` : ""}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
