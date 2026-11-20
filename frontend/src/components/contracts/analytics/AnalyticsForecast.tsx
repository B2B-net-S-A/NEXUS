"use client";

import { useState } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import {
  forecastAxis,
  forecastChange,
  forecastMonthLabel,
  type Forecast,
  type ForecastMonth,
} from "@/lib/contract-analytics";
import { formatPctPl, formatWholeMoney, formatWholeNumber } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

const PLOT_H = 104;

function label(m: ForecastMonth): string {
  return forecastMonthLabel(m.month, m.month_label);
}

/** „3,17 mln zł” przy milionach, inaczej pełne złote. */
function axisAmount(value: number): string {
  if (Math.abs(value) >= 1_000_000) {
    return `${(value / 1_000_000).toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} mln zł`;
  }
  return formatWholeMoney(value);
}

/** Smukła linia marży z osią przyciętą do zakresu zmian i dymkiem miesiąca. */
function ForecastLine({ months }: { months: ForecastMonth[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const { hi, lo } = forecastAxis(months.map((m) => m.margin));
  const n = months.length;
  const xPct = (i: number) => (n === 1 ? 50 : (i / (n - 1)) * 100);
  const yPx = (v: number) => ((hi - v) / (hi - lo)) * PLOT_H;
  const path = months
    .map((m, i) => `${i === 0 ? "M" : "L"}${(xPct(i) * 10).toFixed(1)},${yPx(m.margin).toFixed(1)}`)
    .join(" ");
  const first = months[0];
  const last = months[n - 1];
  const step = n > 1 ? 100 / (n - 1) : 100;
  const h = hover != null ? months[hover] : null;
  const prev = hover != null && hover > 0 ? months[hover - 1] : null;
  const hx = hover != null ? xPct(hover) : 0;
  const ends = n === 1 ? [0] : [0, n - 1];

  return (
    <div className="relative mx-2 mt-2" style={{ height: PLOT_H + 24 }} onMouseLeave={() => setHover(null)} aria-hidden>
      <svg
        viewBox={`0 0 1000 ${PLOT_H}`}
        preserveAspectRatio="none"
        className="absolute inset-x-0 top-0 w-full overflow-visible"
        style={{ height: PLOT_H }}
      >
        <path
          d={path}
          fill="none"
          className="stroke-primary"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      {/* Oś czasu: kreska, znaczniki miesięcy, podpis tylko pierwszego i ostatniego. */}
      <div className="absolute inset-x-0 border-t border-border" style={{ top: PLOT_H }} />
      {months.map((m, i) => (
        <span key={m.month} className="absolute h-1 w-px bg-border" style={{ left: `${xPct(i)}%`, top: PLOT_H }} />
      ))}
      <span className="absolute left-0 text-[11.5px] text-muted-foreground" style={{ top: PLOT_H + 6 }}>
        {label(first)}
      </span>
      {n > 1 ? (
        <span className="absolute right-0 text-[11.5px] text-muted-foreground" style={{ top: PLOT_H + 6 }}>
          {label(last)}
        </span>
      ) : null}
      {ends.map((i) => (
        <span
          key={`dot-${i}`}
          className="absolute size-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary ring-2 ring-card"
          style={{ left: `${xPct(i)}%`, top: yPx(months[i].margin) }}
        />
      ))}
      <span
        className="absolute left-0 whitespace-nowrap text-[12.5px] font-semibold tabular-nums text-foreground"
        style={{ top: yPx(first.margin) - 24 }}
      >
        {formatWholeMoney(first.margin)}
      </span>
      {n > 1 ? (
        <span
          className="absolute right-0 whitespace-nowrap text-[12.5px] font-semibold tabular-nums text-foreground"
          style={{ top: yPx(last.margin) - 24 }}
        >
          {formatWholeMoney(last.margin)}
        </span>
      ) : null}
      {/* Warstwa najechania: kolumna na miesiąc, kreska, kropka i dymek. */}
      {months.map((m, i) => {
        const left = Math.max(0, xPct(i) - step / 2);
        const right = Math.min(100, xPct(i) + step / 2);
        return (
          <span
            key={`hit-${m.month}`}
            className="absolute top-0 cursor-default"
            style={{ left: `${left}%`, width: `${right - left}%`, height: PLOT_H }}
            onMouseEnter={() => setHover(i)}
          />
        );
      })}
      {h ? (
        <>
          <span className="pointer-events-none absolute top-0 w-px bg-foreground/25" style={{ left: `${hx}%`, height: PLOT_H }} />
          <span
            className="pointer-events-none absolute size-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary ring-2 ring-card"
            style={{ left: `${hx}%`, top: yPx(h.margin) }}
          />
          <div
            className={cn(
              "pointer-events-none absolute z-10 w-max rounded-md border border-border bg-popover px-2.5 py-1.5 text-[12px] leading-4 text-popover-foreground shadow-md",
              hx < 15 ? "translate-x-2" : hx > 85 ? "-translate-x-[calc(100%+8px)]" : "-translate-x-1/2",
            )}
            style={{ left: `${hx}%`, top: hx < 15 || hx > 85 ? 0 : -8 }}
          >
            <p className="font-semibold text-foreground">{label(h)}</p>
            <p className="tabular-nums">
              Marża {formatWholeMoney(h.margin)}
              {prev ? (
                <span className="text-muted-foreground">
                  {" "}
                  ({formatWholeMoney(h.margin - prev.margin, "PLN", true)} wobec poprzedniego)
                </span>
              ) : null}
            </p>
            <p className="tabular-nums text-muted-foreground">
              Przychód {formatWholeMoney(h.revenue)} · {countPl(h.active_count, "kontrakt", "kontrakty", "kontraktów")}
            </p>
          </div>
        </>
      ) : null}
    </div>
  );
}

/** Miesiące prognozy w tabeli — widoczne po „Pokaż miesiące”, zawsze dla czytników ekranu. */
function ForecastTable({ months, visible }: { months: ForecastMonth[]; visible: boolean }) {
  return (
    <table className={cn("mt-2 w-full text-[12.5px]", !visible && "sr-only")}>
      <caption className="sr-only">Prognoza marży i przychodu na kolejne miesiące</caption>
      <thead>
        <tr className="border-b border-border">
          <th scope="col" className={cn(CALM_HEAD, "py-1.5 pr-3 text-left")}>
            Miesiąc
          </th>
          <th scope="col" className={cn(CALM_HEAD, "px-3 py-1.5 text-right")}>
            Marża, zł
          </th>
          <th scope="col" className={cn(CALM_HEAD, "px-3 py-1.5 text-right")}>
            Przychód, zł
          </th>
          <th scope="col" className={cn(CALM_HEAD, "py-1.5 pl-3 text-right")}>
            Kontrakty
          </th>
        </tr>
      </thead>
      <tbody>
        {months.map((m) => (
          <tr key={m.month} className={cn(CALM_ROW, "last:border-b-0")}>
            <td className="py-1.5 pr-3 text-foreground">{label(m)}</td>
            <td className={cn(CALM_AMOUNT, "px-3 py-1.5 font-medium")}>{formatWholeNumber(m.margin)}</td>
            <td className={cn(CALM_AMOUNT, "px-3 py-1.5 text-muted-foreground")}>{formatWholeNumber(m.revenue)}</td>
            <td className={cn(CALM_AMOUNT, "py-1.5 pl-3 text-muted-foreground")}>
              {countPl(m.active_count, "kontrakt", "kontrakty", "kontraktów")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * Prognoza (wariant A): smukła linia marży miesięcznej na 12 miesięcy z osią
 * przyciętą do zakresu zmian. Brak kursu NBP zostaje widoczny nad linią —
 * kwoty w tych walutach serwer pomija, nie przelicza 1:1.
 */
export function AnalyticsForecast({ query }: { query: UseQueryResult<Forecast> }) {
  const [table, setTable] = useState(false);
  const f = query.data;
  const months = f?.months ?? [];
  const change = forecastChange(months);
  const last = months[months.length - 1];
  const { lo } = forecastAxis(months.map((m) => m.margin));
  const fxWarnings = f?.fx_warnings ?? [];
  const state = resolveViewState({ isLoading: query.isLoading, isError: query.isError, error: query.error });

  return (
    <section className="rounded-xl border border-border bg-card px-4 pb-3 pt-3 shadow-xs">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4">
        <h2 className="text-[14px] font-semibold text-foreground">Marża miesięczna — prognoza na 12 miesięcy</h2>
        {query.isSuccess && change && last ? (
          <p className="text-[12.5px] text-muted-foreground">
            Do {label(last)}:{" "}
            <span className="font-semibold tabular-nums text-foreground">
              {formatWholeMoney(change.change, "PLN", true)} / mies.
            </span>
            {change.pct != null ? (
              <span className="tabular-nums">
                {" "}
                ({change.pct > 0 ? "+" : change.pct < 0 ? "−" : ""}
                {formatPctPl(Math.abs(change.pct))})
              </span>
            ) : null}
          </p>
        ) : null}
      </div>
      {query.isLoading ? (
        <p className="py-6 text-[13px] text-muted-foreground">Ładowanie prognozy…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} className="mt-2" onRetry={() => void query.refetch()} />
      ) : months.length === 0 ? (
        <p className="py-6 text-[13px] text-muted-foreground">Brak żywych kontraktów — nie ma czego prognozować.</p>
      ) : (
        <>
          {f?.fx_missing || fxWarnings.length > 0 ? (
            <div
              role="alert"
              className="mt-2 flex items-start gap-2 rounded-lg border border-warning/25 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <div className="space-y-0.5">
                {fxWarnings.length > 0 ? (
                  fxWarnings.map((w) => <p key={w}>{w}</p>)
                ) : (
                  <p>
                    Prognoza jest niepełna — dla części walut brakuje kursu NBP, a te kwoty zostały pominięte
                    w sumach.
                  </p>
                )}
              </div>
            </div>
          ) : null}
          <ForecastLine months={months} />
          <ForecastTable months={months} visible={table} />
          <div className="mt-1 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <p className="text-[11.5px] leading-4 text-muted-foreground">
              Liczy znane daty startu i końca umów; umowy bez daty końca trwają dalej, nowej sprzedaży nie
              zakłada.
              {lo > 0 ? ` Oś pionowa zaczyna się od ${axisAmount(lo)}, nie od zera.` : ""}
            </p>
            <Button
              type="button"
              variant="tertiary"
              size="sm"
              className="h-auto px-0 py-0.5"
              aria-expanded={table}
              onClick={() => setTable((v) => !v)}
            >
              {table ? "Ukryj miesiące" : "Pokaż miesiące"}
            </Button>
          </div>
        </>
      )}
    </section>
  );
}
