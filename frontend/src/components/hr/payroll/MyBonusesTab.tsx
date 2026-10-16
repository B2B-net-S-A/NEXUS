"use client";

import { InlineStats, type InlineStat } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useMyPayroll, type MyPayroll } from "@/lib/api/hr-payroll";
import { resolveViewState } from "@/lib/view-state";

import { BonusTable } from "./BonusTable";
import { formatDay, formatMoney, warsawToday } from "./payroll-format";

/** Liczby nad listą: moja stawka i suma przyznanych premii w tym roku (per waluta). */
export function myStats(data: MyPayroll, today: string = warsawToday()): InlineStat[] {
  const year = Number(today.slice(0, 4));
  const sums: Record<string, number> = {};
  for (const bonus of data.bonuses) {
    if (bonus.status !== "assigned" || bonus.period_year !== year) continue;
    sums[bonus.currency] = (sums[bonus.currency] ?? 0) + Number(bonus.amount);
  }
  const stats: InlineStat[] = [
    {
      id: "rate",
      label: data.current_rate
        ? `moja stawka od ${formatDay(data.current_rate.effective_from)}`
        : "moja stawka",
      value: data.current_rate
        ? `${formatMoney(data.current_rate.hourly_rate, data.current_rate.currency)}/h`
        : "nie ustawiona",
    },
  ];
  const entries = Object.entries(sums);
  stats.push({
    id: "bonuses",
    label: `premie przyznane w ${year}`,
    value:
      entries.length === 0
        ? formatMoney(0)
        : entries.map(([currency, total]) => formatMoney(total, currency)).join(" · "),
  });
  const waiting = data.bonuses.filter((b) => b.status === "proposed").length;
  if (waiting > 0) stats.push({ id: "waiting", label: "w drodze", value: waiting });
  return stats;
}

/**
 * „Mój czas → Premie”: moje premie (przyznane i w drodze) i — tylko dla mnie —
 * moja stawka. Przełożony tu nie zagląda; jego widok zespołu jest w Płacach.
 */
export function MyBonusesTab() {
  const me = useMyPayroll();
  const data = me.data;
  const visible = (data?.bonuses ?? []).filter((bonus) => bonus.status !== "cancelled" || bonus.cancel_reason === "manual");
  const state = resolveViewState({
    isLoading: me.isLoading,
    isError: me.isError,
    error: me.error,
    isSuccess: me.isSuccess,
    isEmpty: visible.length === 0,
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
      <InlineStats id="my-bonuses-stats" stats={myStats(data)} />
      {state === "empty" ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          Nie masz jeszcze premii. Premie z placementów pojawią się tu same, gdy kontrakt ruszy.
        </div>
      ) : (
        <BonusTable rows={visible} showRecipient={false} minWidth="min-w-[600px]" />
      )}
      {data.rates.length > 1 ? (
        <details className="text-sm text-muted-foreground">
          <summary className="cursor-pointer select-none">Historia mojej stawki</summary>
          <ul className="mt-2 space-y-1">
            {data.rates.map((rate) => (
              <li key={rate.id}>
                {formatDay(rate.effective_from)}
                {rate.effective_to ? ` – ${formatDay(rate.effective_to)}` : " – teraz"}:{" "}
                <span className="font-medium text-foreground">
                  {formatMoney(rate.hourly_rate, rate.currency)}/h
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
