"use client";

import { InlineStats, type InlineStat } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useMyHrProfile, type EmploymentType } from "@/lib/api/hr";
import { useMyPayroll, useMySettlement, type MyPayroll, type MySettlement } from "@/lib/api/hr-payroll";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";
import { formatMoney } from "@/lib/money";
import { formatIsoDatePl } from "@/lib/date-pl";
import { capitalize, employmentTerms } from "@/lib/hr-employment-terms";

import { BonusStagesTable } from "../me/BonusStagesTable";
import { MySettlementCard } from "../me/MySettlementCard";
import { showsPreviousYear } from "../me/settlement-format";
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
 * wypłacone w roku (premie z zamkniętych miesięcy). W styczniu „wypłacone”
 * są za poprzedni rok: styczeń zamyka się dopiero w lutym, więc liczba
 * bieżącego roku byłaby zerem (audyt A2, 19.10.2026). Przy B2B i zleceniu
 * „wynagrodzenie dodatkowe” zamiast „premii” (decyzja Artura 21.10.2026).
 */
export function myStats(
  data: MyPayroll,
  today: string = warsawToday(),
  settlement?: MySettlement,
  form?: EmploymentType | null,
): InlineStat[] {
  const words = employmentTerms(form);
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
          : `Szacunek z reguł ${words.bonuses_genitive}; kwotę zatwierdzają Płace.`,
    });
  }
  stats.push({
    id: "bonuses",
    label: `${words.bonuses} przyznane w ${year}`,
    value: totalsLabel(assignedInYear(data.bonuses, year)),
  });
  const paidYear = showsPreviousYear(today) ? year - 1 : year;
  if (settlement && settlement.year === paidYear) {
    stats.push({
      id: "paid",
      label: `${words.bonuses} wypłacone w ${paidYear}`,
      value: totalsLabel(settlement.bonuses_paid),
      // R11: przy włączonych rozliczeniach liczą się premie z opłaconych rozliczeń.
      title:
        (settlement as MySettlement & { bonuses_rule?: string }).bonuses_rule === "paid_settlement"
          ? `${capitalize(words.bonuses)} z opłaconych rozliczeń miesięcy.`
          : `${capitalize(words.bonuses)} z miesięcy zamkniętych w płacach.`,
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
  // Styczeń: grudzień i premie wypłacone w poprzednim roku (audyt A2, 19.10.2026).
  const january = showsPreviousYear(today);
  const lastYear = useMySettlement(year - 1, january);
  const profile = useMyHrProfile();
  const form = profile.data?.has_profile ? profile.data.employment_type : null;
  const words = employmentTerms(form);
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
    isLoading: settlement.isLoading || (january && lastYear.isLoading),
    isError: settlement.isError || (january && lastYear.isError),
    error: settlement.error ?? (january ? lastYear.error : null),
    isSuccess: settlement.isSuccess && (!january || lastYear.isSuccess),
  });
  const settlementData: MySettlement | undefined =
    settlement.data && january && lastYear.data
      ? { ...settlement.data, months: [...settlement.data.months, ...lastYear.data.months] }
      : settlement.data;

  if (state === "loading") {
    return (
      <p className="py-6 text-sm text-muted-foreground">Wczytywanie {words.bonuses_genitive}…</p>
    );
  }
  if (state === "forbidden" || state === "not_found" || state === "error" || !data) {
    return (
      <QueryStateNotice
        state={state === "forbidden" || state === "not_found" ? state : "error"}
        description={
          state === "not_found"
            ? "Moduł Płac nie jest jeszcze włączony."
            : state === "forbidden"
              ? `${capitalize(words.bonuses)} widzą osoby z kartoteką w NEXUSIE.`
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
        stats={myStats(
          data,
          today,
          settlementState === "ready" ? (january ? lastYear.data : settlement.data) : undefined,
          form,
        )}
      />
      {state === "empty" ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          Nie masz jeszcze {words.bonuses_genitive}. {capitalize(words.bonus)} z placementu
          pojawi się tu od podpisania umowy z konsultantem.
        </div>
      ) : (
        <BonusStagesTable items={items} />
      )}
      <MySettlementCard
        state={settlementState}
        data={settlementData}
        form={form}
        onRetry={() => {
          void settlement.refetch();
          if (january) void lastYear.refetch();
        }}
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
