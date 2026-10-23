"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import {
  insightsApi,
  insightsBoardApi,
  insightsQueryKeys,
  type InFlightAcceptance,
  type InsightsBoardFlowsResponse,
  type InsightsPeriodParams,
  type InsightsYoYResponse,
} from "@/lib/insights-api";
import { firmaSentence, signedCount } from "@/lib/insights-firma";
import { daysLabel, monthForecast } from "@/lib/insights-in-flight";
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
import { TeamFunnelPanel } from "./team/TeamFunnelPanel";
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

const SAME_STRETCH_LABEL: Record<string, string> = {
  week: "wobec tego samego odcinka poprzedniego tygodnia",
  month: "wobec tego samego odcinka poprzedniego miesiąca",
  quarter: "wobec tego samego odcinka poprzedniego kwartału",
  year: "wobec tego samego odcinka poprzedniego roku",
  custom: "wobec tego samego odcinka poprzedniego okresu",
};

/**
 * Podpis delty placementów. Okres W TOKU backend porównuje z tym samym
 * odcinkiem poprzedniego (`placements_previous_window.same_stretch`, runda 6
 * audytu) — „wobec poprzedniego miesiąca" obiecywałby pełny miesiąc.
 */
export function placementsDeltaLabel(
  period: string,
  sameStretch: boolean | undefined,
): string {
  const labels = sameStretch ? SAME_STRETCH_LABEL : PREVIOUS_LABEL;
  return labels[period] ?? labels.custom;
}

/**
 * Firma — „Jak idzie firma?” (v3, 22.10.2026: + ruch konsultantów, lejek
 * z „stoi dziś” i prognozą okresu, akceptacje, skuteczność i popyt). Tylko „Moduł Finanse” (admin, Finanse —
 * decyzja Artura 24.09.2026) i Rada nadzorcza (0490); lustro `BoardReader`.
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
  const flowsQuery = useQuery({
    queryKey: insightsQueryKeys.boardFlows(period),
    queryFn: () => insightsBoardApi.boardFlows(period),
  });
  const funnelQuery = useQuery({
    queryKey: ["insights", "recruitment", "funnel", period],
    queryFn: () => insightsApi.recruitmentFunnel(period),
  });
  const inFlightQuery = useQuery({
    queryKey: insightsQueryKeys.inFlight(),
    queryFn: () => insightsApi.inFlight(),
    staleTime: 60 * 1000,
  });

  const board = boardQuery.data;
  const flows = flowsQuery.data;
  const inFlight = inFlightQuery.data;
  const viewState = resolveViewState({
    isLoading: boardQuery.isPending,
    isSuccess: boardQuery.isSuccess,
    isError: boardQuery.isError,
    error: boardQuery.error,
  });
  const prevLabel = PREVIOUS_LABEL[period.period] ?? PREVIOUS_LABEL.custom;
  // Prognoza tylko dla okresu, który trwa — zamknięty kwartał już się skończył.
  const periodOngoing = board ? new Date(board.period.end).getTime() > Date.now() : false;
  const periodForecast =
    board && inFlight && periodOngoing
      ? monthForecast(board.kpis.placements, inFlight.forecast)
      : null;
  const sentence = board
    ? firmaSentence({
        margin:
          board.kpis.finance.margin_monthly_pln === null
            ? null
            : compactPln(board.kpis.finance.margin_monthly_pln),
        marginChangePct: board.comparison.margin_monthly_pln.change_pct,
        net: flows?.consultants.net ?? null,
        endingWithoutContinuation: flows?.ending_without_continuation.contracts ?? null,
        periodForecast,
      })
    : null;

  return (
    <div className="space-y-6">
      <ViewHeader
        question="Jak idzie firma?"
        lede={sentence ?? undefined}
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
              delta={pctDelta(
                board.comparison.placements.change_pct,
                placementsDeltaLabel(
                  period.period,
                  board.comparison.placements_previous_window?.same_stretch,
                ),
              )}
              note={periodForecast ? `z akceptacjami ${periodForecast}` : null}
            />
          </TileRow>
          {board.degraded ? (
            <p className="rounded-lg border border-warning/25 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground">
              {board.degraded.message}
            </p>
          ) : null}
        </>
      )}

      <ConsultantFlowsPanel
        flows={flows}
        isPending={flowsQuery.isPending}
        error={flowsQuery.isError ? flowsQuery.error : null}
        onRetry={() => void flowsQuery.refetch()}
      />

      {funnelQuery.data ? (
        <TeamFunnelPanel
          funnel={funnelQuery.data}
          previous={undefined}
          previousLabel={undefined}
          inFlight={inFlight}
          period={period}
        />
      ) : funnelQuery.isError ? (
        <SectionError
          label="Lejek"
          error={funnelQuery.error}
          onRetry={() => void funnelQuery.refetch()}
        />
      ) : (
        <PanelLoading />
      )}

      {inFlight?.acceptances && inFlight.acceptances.length > 0 ? (
        <AcceptancesList acceptances={inFlight.acceptances} staleDays={inFlight.stale_days} />
      ) : null}

      {board ? (
        <EffectivenessPanel
          hitRatio={board.kpis.hit_ratio_pct}
          closedWithPlacement={board.kpis.jobs_closed_with_placement}
          closed={board.kpis.jobs_closed}
          jobs={flows?.jobs ?? null}
        />
      ) : null}

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

      <details className="text-xs text-muted-foreground">
        <summary className="min-h-9 cursor-pointer py-2 font-semibold text-primary">
          Jak liczymy widok Firma?
        </summary>
        <p className="max-w-4xl leading-relaxed">
          Kwoty porównujemy z poprzednim okresem, nie rok do roku: ewidencja
          kontraktów sprzed 2026 jest niepełna, więc kwoty rok do roku
          pokazałyby wzrost, którego nie było. Rok do roku pokazuje wykres —
          placementy i hit ratio z historii pipeline'u. Ruch konsultantów liczymy
          z kontraktów: start kontraktu w oknie, zejście = koniec kontraktu
          zakończonego (rezygnacje to część zejść, bez „klient zabrał”).
          „Kończą się w 30 dni” — zamówienie okresowe kończy się w 30 dni
          i nic go nie przedłuża (ta sama reguła co zakładka „Kończące się 30d”).
          Akceptacje liczą się od 12.10.2026; szacunek placementów z akceptacji —
          od 10 rozstrzygniętych.
        </p>
      </details>
    </div>
  );
}

function ConsultantFlowsPanel({
  flows,
  isPending,
  error,
  onRetry,
}: {
  flows: InsightsBoardFlowsResponse | undefined;
  isPending: boolean;
  error: unknown;
  onRetry: () => void;
}) {
  if (isPending) return <PanelLoading />;
  if (error || !flows) {
    return <SectionError label="Ruch konsultantów" error={error} onRetry={onRetry} />;
  }
  const c = flows.consultants;
  const p = flows.previous_consultants;
  return (
    <Panel title="Ruch konsultantów w okresie" hint="z kontraktów">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <FlowCell label="Przyszli" value={signedCount(c.starts)} note={`poprzednio ${p.starts}`} tone="good" />
        <FlowCell
          label="Odeszli"
          value={c.ends === 0 ? "0" : signedCount(-c.ends)}
          note={`w tym rezygnacje: ${c.resignations} · poprzednio ${p.ends}`}
          tone={c.ends > 0 ? "bad" : "neutral"}
        />
        <FlowCell label="Netto" value={signedCount(c.net)} note={`poprzednio ${signedCount(p.net)}`} tone="neutral" />
        <FlowCell
          label={`Kończą się w ${flows.ending_without_continuation.days} dni`}
          value={String(flows.ending_without_continuation.contracts)}
          note="bez kontynuacji zamówienia"
          tone={flows.ending_without_continuation.contracts > 0 ? "warn" : "neutral"}
        />
      </div>
    </Panel>
  );
}

const FLOW_TONE = {
  good: "text-success-muted-foreground",
  bad: "text-destructive",
  warn: "text-warning-muted-foreground",
  neutral: "text-foreground",
} as const;

function FlowCell({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note: string;
  tone: keyof typeof FLOW_TONE;
}) {
  return (
    <div className="rounded-lg bg-muted/50 p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={cn("text-2xl font-bold tabular-nums", FLOW_TONE[tone])}>{value}</p>
      <p className="text-xs text-muted-foreground">{note}</p>
    </div>
  );
}

function AcceptancesList({
  acceptances,
  staleDays,
}: {
  acceptances: InFlightAcceptance[];
  staleDays: number;
}) {
  return (
    <details className="rounded-xl border border-border bg-card shadow-xs">
      <summary className="flex min-h-11 cursor-pointer items-center justify-between gap-3 px-4 text-sm font-semibold text-foreground">
        Akceptacje do domknięcia: {acceptances.length} — klient, rekrutacja, od kiedy, umowa, DL
        <span className="text-primary">Pokaż ▾</span>
      </summary>
      <div className="overflow-x-auto border-t border-border px-4 py-2">
        <table className="w-full min-w-[36rem] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="py-2 pr-3 font-semibold">Klient</th>
              <th className="py-2 pr-3 font-semibold">Rekrutacja</th>
              <th className="py-2 pr-3 font-semibold">Od kiedy</th>
              <th className="py-2 pr-3 font-semibold">Umowa</th>
              <th className="py-2 font-semibold">Delivery Lead</th>
            </tr>
          </thead>
          <tbody>
            {acceptances.map((a) => (
              <tr key={`${a.job_id}-${a.since}-${a.stage_key}`} className="border-b border-border/60">
                <td className="py-2 pr-3 text-foreground">{a.client_name ?? "—"}</td>
                <td className="py-2 pr-3 text-foreground">{a.job_title}</td>
                <td
                  className={cn(
                    "py-2 pr-3 tabular-nums",
                    a.days > staleDays ? "font-semibold text-warning-muted-foreground" : "text-muted-foreground",
                  )}
                >
                  {daysLabel(a.days)}
                </td>
                <td className="py-2 pr-3 text-muted-foreground">
                  {a.stage_key === "acceptance" ? "—" : a.stage_label.replace("Umowa ", "")}
                </td>
                <td className="py-2 text-muted-foreground">{a.delivery_lead_name ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="py-2 text-xs text-muted-foreground">
          Bez nazwisk kandydatów. Rekrutacja nie jest linkiem dla kont bez dostępu do Rekrutacji.
        </p>
      </div>
    </details>
  );
}

function EffectivenessPanel({
  hitRatio,
  closedWithPlacement,
  closed,
  jobs,
}: {
  hitRatio: number | null;
  closedWithPlacement: number;
  closed: number;
  jobs: InsightsBoardFlowsResponse["jobs"] | null;
}) {
  return (
    <Panel title="Skuteczność i popyt">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <FlowCell
          label="Hit ratio"
          value={hitRatio === null ? "—" : `${Math.round(hitRatio)}%`}
          note={`${closedWithPlacement} z ${closed} zamkniętych rekrutacji`}
          tone="neutral"
        />
        <FlowCell
          label="Otwarte rekrutacje"
          value={jobs ? String(jobs.open) : "…"}
          note={jobs ? `u ${jobs.open_clients} klientów · stan na dziś` : ""}
          tone="neutral"
        />
        <FlowCell
          label="Nowe rekrutacje w okresie"
          value={jobs ? String(jobs.new) : "…"}
          note={jobs ? `poprzednio ${jobs.previous_new}` : ""}
          tone="neutral"
        />
      </div>
      <Link
        href={reportHref("czas-konwersje")}
        className="w-fit text-sm font-semibold text-primary hover:underline"
      >
        Czas do placementu i konwersje →
      </Link>
    </Panel>
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
