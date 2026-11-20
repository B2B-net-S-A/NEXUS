"use client";

import type { UseQueryResult } from "@tanstack/react-query";
import {
  marginFigureNote,
  withoutRevenueNote,
  type MarginTotals,
  type UtilizationData,
} from "@/lib/contract-analytics";
import { formatPctPl, formatWholeMoney } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";

function Figure({ label, value, note }: { label: string; value: string; note?: React.ReactNode }) {
  return (
    <div className="min-w-0 px-4 py-3">
      <p className="text-[11.5px] leading-4 text-muted-foreground">{label}</p>
      <p className="font-display text-[20px] font-semibold leading-7 tabular-nums text-foreground">{value}</p>
      {note ? <div className="text-[11.5px] leading-4 text-muted-foreground">{note}</div> : null}
    </div>
  );
}

/**
 * Rząd czterech liczb (wariant A): marża i przychód z `margin-totals` (sumy
 * nie zależą od rankingu obok), utylizacja i ławka z `utilization`. Awaria
 * albo brak kursu FX to „—” ze zdaniem, nigdy sformatowane zero.
 */
export function AnalyticsKeyFigures({
  totals,
  util,
  fxMissing,
}: {
  totals: UseQueryResult<MarginTotals>;
  util: UseQueryResult<UtilizationData>;
  /** Którykolwiek wiersz rankingu albo suma bez kursu FX. */
  fxMissing: boolean;
}) {
  const t = totals.data;
  const u = util.data;
  const known = totals.isSuccess && t !== undefined && !t.fx_missing;
  const moneyGap = (failed: string) =>
    totals.isLoading ? "Ładowanie…" : fxMissing ? "Niepełne dane — brak kursu FX" : failed;
  const utilGap = (failed: string) => (util.isError ? failed : "Ładowanie…");
  const withoutRevenue = known ? withoutRevenueNote(t.contracts_without_revenue_leg) : undefined;

  return (
    <section
      aria-label="Najważniejsze liczby"
      className="grid grid-cols-2 divide-border/60 rounded-xl border border-border bg-card shadow-xs lg:grid-cols-4 lg:divide-x"
    >
      <Figure
        label="Marża miesięcznie"
        value={known ? formatWholeMoney(t.total_monthly_margin) : "—"}
        note={known ? marginFigureNote(t) : moneyGap("Nie udało się pobrać marży")}
      />
      <Figure
        label="Przychód miesięcznie"
        value={known ? formatWholeMoney(t.total_monthly_revenue) : "—"}
        note={
          known ? (
            <>
              <span className="block">
                {countPl(t.active_contracts, "kontrakt", "kontrakty", "kontraktów")} u{" "}
                {countPl(t.clients, "klienta", "klientów", "klientów")}
              </span>
              {withoutRevenue ? <span className="block">{withoutRevenue}</span> : null}
            </>
          ) : (
            moneyGap("Nie udało się pobrać przychodu")
          )
        }
      />
      <Figure
        label="Utylizacja"
        value={u && u.utilization_pct !== null ? formatPctPl(u.utilization_pct) : "—"}
        note={
          u
            ? u.utilization_pct === null
              ? "Brak konsultantów do policzenia"
              : `${u.candidates_active} z ${u.total_candidates} konsultantów pracuje`
            : utilGap("Nie udało się pobrać utylizacji")
        }
      />
      <Figure
        label="Na ławce"
        value={u ? countPl(u.candidates_on_bench, "osoba", "osoby", "osób") : "—"}
        note={
          u
            ? u.avg_bench_days != null
              ? `średnio ${countPl(Math.round(u.avg_bench_days), "dzień", "dni", "dni")} bez kontraktu`
              : "bez danych o czasie na ławce"
            : utilGap("Nie udało się pobrać danych o ławce")
        }
      />
    </section>
  );
}
