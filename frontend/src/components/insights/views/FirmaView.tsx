"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsPeriodParams,
  type InsightsYoYResponse,
} from "@/lib/insights-api";
import { buildRadaCsvExport } from "@/lib/insights-csv";
import { reportHref } from "@/lib/insights-reports";
import {
  compactPln,
  monthGenitive,
  pctDelta,
  topWithRest,
  yearToDate,
} from "@/lib/insights-views";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { PeriodPicker } from "@/components/insights/PeriodPicker";
import { useInsightsPeriod } from "@/components/insights/useInsightsPeriod";
import { SectionError } from "@/components/insights/sections/_shared";
import { Panel, PanelLoading, Takeaway, Tile, TileRow, ViewHeader } from "./ViewKit";

export const FIRMA_DEFAULT_PERIOD: InsightsPeriodParams = {
  period: "quarter",
  offset: 0,
};

const PREVIOUS_LABEL: Record<string, string> = {
  week: "wobec poprzedniego tygodnia",
  month: "wobec poprzedniego miesiąca",
  quarter: "wobec poprzedniego kwartału",
  year: "wobec poprzedniego roku",
  custom: "wobec poprzedniego okresu",
};

/**
 * Firma — „Jak zarabia firma?". Tylko admin i Finanse (decyzja Artura
 * 24.09.2026; lustro `BoardReader`).
 *
 * Kwoty porównujemy z poprzednim okresem, NIE rok do roku: ewidencja
 * kontraktów jest młodsza niż firma, więc porównanie lat opisuje głównie
 * rozrastanie się ewidencji. Rok do roku idzie wyłącznie dla metryk
 * z historii pipeline'u (placementy, hit ratio).
 */
export function FirmaView() {
  const { period, setPeriod } = useInsightsPeriod(FIRMA_DEFAULT_PERIOD);
  const boardQuery = useQuery({
    queryKey: insightsQueryKeys.board(period),
    queryFn: () => insightsBoardApi.board(period),
  });
  const rankingQuery = useQuery({
    queryKey: insightsQueryKeys.clientsRanking(period),
    queryFn: () => insightsBoardApi.clientsRanking(period),
  });
  const yoyQuery = useQuery({
    queryKey: insightsQueryKeys.boardYoY({ years: 2 }),
    queryFn: () => insightsBoardApi.boardYoY({ years: 2 }),
    staleTime: 15 * 60 * 1000,
  });

  const board = boardQuery.data;
  const viewState = resolveViewState({
    isLoading: boardQuery.isPending,
    isSuccess: boardQuery.isSuccess,
    isError: boardQuery.isError,
    error: boardQuery.error,
  });
  const prevLabel = PREVIOUS_LABEL[period.period] ?? PREVIOUS_LABEL.custom;

  return (
    <div className="space-y-6">
      <ViewHeader
        question="Jak zarabia firma?"
        lede="Kafle porównujemy z poprzednim okresem — ewidencja kontraktów sprzed 2026 jest niepełna, więc kwoty rok do roku pokazałyby wzrost, którego nie było. Rok do roku pokazuje wykres: placementy i hit ratio z historii pipeline'u."
        actions={
          <PeriodPicker
            value={period}
            onChange={setPeriod}
            defaultValue={FIRMA_DEFAULT_PERIOD}
            resolved={board?.period ?? null}
            csv={buildRadaCsvExport(board, rankingQuery.data)}
          />
        }
      />

      {viewState === "loading" ? (
        <PanelLoading />
      ) : isBlockingViewState(viewState) || !board ? (
        <SectionError
          label="Firma"
          error={boardQuery.error}
          onRetry={() => void boardQuery.refetch()}
        />
      ) : (
        <>
          <TileRow>
            <Tile
              label="Przychód / mc"
              value={compactPln(board.kpis.finance.revenue_monthly_pln)}
              delta={pctDelta(
                board.comparison.revenue_monthly_pln.change_pct,
                prevLabel,
              )}
              note={`wycena na ${board.kpis.finance.asof}`}
            />
            <Tile
              label="Marża / mc"
              value={compactPln(board.kpis.finance.margin_monthly_pln)}
              delta={pctDelta(
                board.comparison.margin_monthly_pln.change_pct,
                prevLabel,
              )}
              note={
                board.kpis.finance.margin_pct === null
                  ? null
                  : `${board.kpis.finance.margin_pct.toLocaleString("pl-PL", { maximumFractionDigits: 1 })}% przychodu`
              }
            />
            <Tile
              label="Pracujący konsultanci"
              value={board.kpis.finance.active_consultants.toLocaleString("pl-PL")}
              delta={pctDelta(
                board.comparison.active_consultants.change_pct,
                prevLabel,
              )}
            />
            <Tile
              label="Placementy w okresie"
              value={board.kpis.placements.toLocaleString("pl-PL")}
              delta={pctDelta(board.comparison.placements.change_pct, prevLabel)}
            />
          </TileRow>
          {board.degraded ? (
            <p className="rounded-lg border border-warning/25 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground">
              {board.degraded.message}
            </p>
          ) : null}
        </>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <YearOverYearPanel
          data={yoyQuery.data}
          isPending={yoyQuery.isPending}
          error={yoyQuery.isError ? yoyQuery.error : null}
          onRetry={() => void yoyQuery.refetch()}
        />
        <Panel title="Klienci" hint="marża / mc">
          {rankingQuery.isPending ? (
            <PanelLoading />
          ) : rankingQuery.isError || !rankingQuery.data ? (
            <SectionError
              label="Klienci"
              error={rankingQuery.error}
              onRetry={() => void rankingQuery.refetch()}
            />
          ) : (
            <ClientsConcentration
              rows={rankingQuery.data.clients.map((c) => ({
                name: c.name,
                value: c.monthly_margin_total,
              }))}
            />
          )}
          <Link
            href={reportHref("ranking-klientow")}
            className="text-sm font-semibold text-primary hover:underline"
          >
            Ranking wszystkich klientów →
          </Link>
        </Panel>
      </div>
    </div>
  );
}

function ClientsConcentration({
  rows,
}: {
  rows: { name: string; value: number | null }[];
}) {
  const { top, rest, total, top3Share } = topWithRest(rows, 7);
  if (total <= 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Brak wycenionej marży w tym okresie.
      </p>
    );
  }
  const max = Math.max(...top.map((r) => r.value ?? 0), rest);
  return (
    <div className="space-y-3">
      {top3Share !== null ? (
        <Takeaway>
          Trzech największych klientów daje {top3Share}% marży. Odejście
          największego to {compactPln(top[0]?.value ?? null)} miesięcznie.
        </Takeaway>
      ) : null}
      <ol className="space-y-1.5">
        {[...top, { name: "Pozostali", value: rest, share: null }].map((row, i) => (
          <li
            key={`${row.name}-${i}`}
            className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)_5.5rem] items-center gap-3 text-sm"
          >
            <span className="truncate text-foreground" title={row.name}>
              {row.name}
            </span>
            <span className="h-3 rounded bg-muted">
              <span
                className={cn(
                  "block h-3 rounded",
                  row.name === "Pozostali" ? "bg-muted-foreground/40" : "bg-primary",
                )}
                style={{ width: `${(100 * (row.value ?? 0)) / (max || 1)}%` }}
              />
            </span>
            <span className="text-right tabular-nums text-muted-foreground">
              {compactPln(row.value)}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

type YoyMetric = "placements" | "hit_ratio_pct";

function YearOverYearPanel({
  data,
  isPending,
  error,
  onRetry,
}: {
  data: InsightsYoYResponse | undefined;
  isPending: boolean;
  error: unknown;
  onRetry: () => void;
}) {
  const [metric, setMetric] = useState<YoyMetric>("placements");
  const switcher = (
    <div role="group" aria-label="Metryka" className="inline-flex gap-0.5 rounded-lg bg-muted p-1">
      {(
        [
          ["placements", "Placementy"],
          ["hit_ratio_pct", "Hit ratio"],
        ] as const
      ).map(([value, label]) => (
        <button
          key={value}
          type="button"
          aria-pressed={metric === value}
          onClick={() => setMetric(value)}
          className={cn(
            "min-h-8 rounded-md px-3 text-xs font-semibold",
            metric === value
              ? "bg-card text-foreground shadow-xs"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );

  return (
    <Panel title="Rok do roku" actions={switcher}>
      {isPending ? (
        <PanelLoading />
      ) : error || !data ? (
        <SectionError label="Rok do roku" error={error} onRetry={onRetry} />
      ) : (
        <YearOverYearChart data={data} metric={metric} />
      )}
      <Link
        href={reportHref("rok-do-roku")}
        className="text-sm font-semibold text-primary hover:underline"
      >
        Pełne tabele rok do roku →
      </Link>
    </Panel>
  );
}

const MONTHS_SHORT = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"];

function YearOverYearChart({
  data,
  metric,
}: {
  data: InsightsYoYResponse;
  metric: YoyMetric;
}) {
  const years = data.years.slice(-2).map(String);
  const def = data.metrics.find((m) => m.key === metric);
  if (!def || years.length < 2) {
    return <p className="text-sm text-muted-foreground">Brak danych do porównania.</p>;
  }
  const [prevYear, curYear] = years;
  const cur = def.series[curYear] ?? [];
  const prev = def.series[prevYear] ?? [];
  const partial = data.partial_month;
  const fullMonths =
    partial && String(partial.year) === curYear
      ? partial.month - 1
      : cur.filter((v) => v !== null).length;

  // Zdanie: suma (placementy) albo Σlicznik/Σmianownik (hit ratio) za
  // styczeń–ostatni pełny miesiąc w OBU latach.
  let sentence: string | null = null;
  if (metric === "placements") {
    const ytd = yearToDate(cur, prev, fullMonths);
    if (ytd && ytd.previous > 0) {
      const change = Math.round((100 * (ytd.current - ytd.previous)) / ytd.previous);
      sentence = `Od stycznia do ${monthGenitive(fullMonths - 1)} ${curYear}: ${ytd.current} placementów wobec ${ytd.previous} rok wcześniej (${change >= 0 ? "+" : ""}${change}%).`;
    }
  } else if (def.components) {
    const num = data.component_series[def.components.numerator] ?? {};
    const den = data.component_series[def.components.denominator] ?? {};
    const a = yearToDate(num[curYear] ?? [], num[prevYear] ?? [], fullMonths);
    const b = yearToDate(den[curYear] ?? [], den[prevYear] ?? [], fullMonths);
    if (a && b && b.current > 0 && b.previous > 0) {
      const now = Math.round((100 * a.current) / b.current);
      const before = Math.round((100 * a.previous) / b.previous);
      sentence = `Od stycznia do ${monthGenitive(fullMonths - 1)} ${curYear}: hit ratio ${now}% wobec ${before}% rok wcześniej.`;
    }
  }

  const values = [...cur, ...prev].filter((v): v is number => v !== null);
  const max = Math.max(1, ...values);
  const W = 640;
  const H = 220;
  const left = 36;
  const bottom = 24;
  const x = (i: number) => left + (i * (W - left - 8)) / 11;
  const y = (v: number) => 8 + (H - bottom - 8) * (1 - v / max);
  const path = (series: ReadonlyArray<number | null>, upTo: number) =>
    series
      .slice(0, upTo)
      .map((v, i) => (v === null ? null : `${x(i)},${y(v)}`))
      .filter(Boolean)
      .join(" ");
  const curEnd = partial && String(partial.year) === curYear ? partial.month : 12;
  const suffix = def.unit === "pct" ? "%" : "";

  return (
    <div className="space-y-3">
      <div className="flex gap-4 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-0.5 w-4 rounded bg-primary" />
          {curYear}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-0.5 w-4 rounded bg-muted-foreground/60" />
          {prevYear}
        </span>
        {partial && String(partial.year) === curYear ? (
          <span>{MONTHS_SHORT[partial.month - 1]} trwa</span>
        ) : null}
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full"
        role="img"
        aria-label={`${def.label}: ${curYear} i ${prevYear}, miesiąc po miesiącu`}
      >
        {[0, 0.5, 1].map((t) => (
          <g key={t}>
            <line
              x1={left}
              x2={W - 8}
              y1={y(max * t)}
              y2={y(max * t)}
              className="stroke-border"
              strokeWidth={1}
            />
            <text
              x={left - 6}
              y={y(max * t) + 4}
              textAnchor="end"
              className="fill-muted-foreground text-[10px]"
            >
              {Math.round(max * t)}
              {suffix}
            </text>
          </g>
        ))}
        <polyline
          points={path(prev, 12)}
          fill="none"
          className="stroke-muted-foreground/60"
          strokeWidth={2}
          strokeLinejoin="round"
        />
        <polyline
          points={path(cur, curEnd)}
          fill="none"
          className="stroke-primary"
          strokeWidth={3}
          strokeLinejoin="round"
        />
        {MONTHS_SHORT.map((m, i) => (
          <text
            key={m}
            x={x(i)}
            y={H - 6}
            textAnchor="middle"
            className="fill-muted-foreground text-[10px]"
          >
            {m}
          </text>
        ))}
      </svg>
      {sentence ? <Takeaway>{sentence}</Takeaway> : null}
    </div>
  );
}
