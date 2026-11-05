"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";

import { cn } from "@/lib/utils";
import { insightsApi, insightsQueryKeys, type InsightsPeriodParams } from "@/lib/insights-api";
import { columnOf, forecastLabel } from "@/lib/insights-in-flight";
import { reportHref } from "@/lib/insights-reports";
import { rankedSignals, stageCount, TEAM_STAGES, type TeamStage } from "@/lib/insights-team-view";
import { addDays, metricFromSlug, WHO_COUNTS_METRICS, type WhoCountsMetric } from "@/lib/kpi-who-counts";
import { useUrlWriter } from "@/lib/url-selection";
import { TeamListReconcileLine, TeamWhoCountsPanel } from "@/components/insights/sections/WhoCountsPanel";
import { SectionError } from "@/components/insights/sections/_shared";

import { PanelLoading } from "../ViewKit";
import { SignalRow } from "./TeamAnswer";
import { TEAM_LIST_SLUG } from "./TeamFunnelPanel";
import { StageTrend, WholeFunnelTrend, type TrendMode } from "./TeamTrendCharts";
import type { TeamViewData } from "./useTeamViewData";

/** Sygnały przy etapie, którego dotyczą; reszta jest w „Najpierw to”. */
const STAGE_SIGNALS: Record<string, readonly string[]> = {
  verified: ["stale_postings", "low_precision"],
  cv_sent: ["dl_send_stale", "no_one_sent"],
  client_interview: ["weak_preps"],
  acceptance: ["stale_acceptances"],
  hired: [],
};

const FUNNEL_METRICS: readonly WhoCountsMetric[] = TEAM_STAGES.map((s) => s.metric);
const WEEKS_TABLE = 8;

function DeltaText({ now, before }: { now: number; before: number | undefined }) {
  if (before === undefined) return null;
  const diff = now - before;
  return (
    <span className="text-xs tabular-nums text-muted-foreground">
      {diff === 0 ? "bez zmian" : `${diff > 0 ? "+" : "−"}${Math.abs(diff).toLocaleString("pl-PL")}`}
    </span>
  );
}

function PeopleBars({
  data,
  stage,
  onOpen,
  openWho,
  openMetric,
}: {
  data: TeamViewData;
  stage: TeamStage;
  onOpen: (who: string) => void;
  openWho: string | null;
  openMetric: WhoCountsMetric | null;
}) {
  if (data.people.isPending) return <PanelLoading />;
  if (data.people.isError) {
    return <SectionError label="Ludzie" error={data.people.error} onRetry={() => void data.people.refetch()} />;
  }
  const value = (row: (typeof data.rows)[number]) => row[stage.rowKey] ?? 0;
  const all = data.rows.filter((row) => value(row) > 0).sort((a, b) => value(b) - value(a));
  const top = all.slice(0, 7);
  const rest = all.slice(7);
  const max = Math.max(1, ...top.map(value));
  if (all.length === 0) {
    return <p className="py-6 text-sm text-muted-foreground">Nikt nie ma jeszcze tego etapu w tym okresie.</p>;
  }
  return (
    <ol className="space-y-0.5">
      {top.map((row) => {
        const open = openWho === String(row.user_id) && openMetric === stage.metric;
        return (
          <li key={row.user_id}>
            <button
              type="button"
              onClick={() => onOpen(String(row.user_id))}
              aria-pressed={open}
              aria-label={`${row.name} · ${stage.label}: ${value(row)}. Pokaż osoby`}
              className={cn("grid w-full grid-cols-[9.5rem_minmax(0,1fr)_2.5rem] items-center gap-2 rounded px-1.5 py-1 text-left text-sm hover:bg-muted", open && "bg-primary/10")}
            >
              <span className="truncate text-foreground">{row.name}</span>
              <span className="h-2 rounded-full bg-muted">
                <span className="block h-2 rounded-full bg-primary" style={{ width: `${(100 * value(row)) / max}%` }} />
              </span>
              <span className="text-right font-semibold tabular-nums text-foreground">{value(row)}</span>
            </button>
          </li>
        );
      })}
      {rest.length > 0 ? (
        <li className="px-1.5 pt-1 text-xs tabular-nums text-muted-foreground">
          Pozostali ({rest.length}): {rest.reduce((sum, row) => sum + value(row), 0)}
        </li>
      ) : null}
    </ol>
  );
}

function StageWeeksTable({ data, onOpen, openMetric, canOpenList }: { data: TeamViewData; onOpen: (metric: WhoCountsMetric) => void; openMetric: WhoCountsMetric | null; canOpenList: boolean }) {
  const query = useQuery({
    queryKey: insightsQueryKeys.weeklyTrend(WEEKS_TABLE),
    queryFn: () => insightsApi.weeklyTrend(WEEKS_TABLE),
    staleTime: 5 * 60 * 1000,
  });
  if (query.isPending) return <PanelLoading />;
  if (query.isError) {
    return <SectionError label="Liczby tydzień po tygodniu" error={query.error} onRetry={() => void query.refetch()} />;
  }
  const weeks = query.data.weeks;
  const head = (iso: string) => `${Number(iso.slice(8, 10))}.${iso.slice(5, 7)}`;
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[46rem] text-sm tabular-nums">
        <thead>
          <tr className="border-b border-border text-xs text-muted-foreground">
            <th scope="col" className="px-3 py-1.5 text-left font-medium">Etap</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">W okresie</th>
            {weeks.map((week) => (
              <th key={week.week_start} scope="col" className="px-1 py-1.5 text-right font-medium">{week.partial ? "trwa" : head(week.week_start)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {TEAM_STAGES.map((stage) => {
            const count = stageCount(data.funnel.data, stage.stage);
            const values = weeks.map((week) => week.counts[stage.stage]);
            const max = Math.max(1, ...values.map((v) => v ?? 0));
            return (
              <tr key={stage.stage} className="h-8 border-b border-border/60 last:border-b-0">
                <td className="whitespace-nowrap px-3 py-1 font-medium text-foreground">{stage.label}</td>
                <td className={cn("px-2 py-1 text-right font-semibold text-foreground", openMetric === stage.metric && "bg-primary/10")}>
                  {canOpenList && count > 0 ? (
                    <button type="button" onClick={() => onOpen(stage.metric)} aria-label={`${stage.label}: ${count}. Pokaż osoby`} className="underline decoration-dotted underline-offset-4 hover:text-primary">
                      {count.toLocaleString("pl-PL")}
                    </button>
                  ) : (
                    count.toLocaleString("pl-PL")
                  )}
                </td>
                {values.map((v, i) => (
                  <td key={weeks[i].week_start} className="px-0.5 py-0.5">
                    <span
                      className={cn("block rounded px-1 text-right", weeks[i].partial || v === null ? "text-muted-foreground" : "text-foreground")}
                      style={v === null || weeks[i].partial ? undefined : { backgroundColor: `hsl(var(--primary) / ${(0.04 + 0.26 * (v / max)).toFixed(3)})` }}
                    >
                      {v ?? "—"}
                    </span>
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Soczewka etapu (05.11.2026): „Cały lejek” pokazuje wszystkie wykresy, a wybrany
 * etap swoją linię, przejście do niego, osoby i sygnały. Zastępuje lejek w dwóch
 * wierszach, słupki ośmiu tygodni i „Do uwagi”: klik mówi, o czym jest reszta ekranu.
 */
export function TeamStageLens({ data, seesTeam, period }: { data: TeamViewData; seesTeam: boolean; period: InsightsPeriodParams }) {
  const searchParams = useSearchParams();
  const { pushUrl, replaceUrl } = useUrlWriter();
  const selected = TEAM_STAGES.find((stage) => stage.stage === searchParams.get("etap")) ?? null;
  const mode: TrendMode = searchParams.get("os") === "miesiac" ? "month" : "week";
  // „Pokaż” przy parach bez osoby z zasługą — widok w tej samej liście, nie w adresie.
  const [withoutCredit, setWithoutCredit] = useState(false);
  const who = searchParams.get("osoba");
  const metric = metricFromSlug(searchParams.get("kto"));
  const teamMetric = who === TEAM_LIST_SLUG ? metric : null;
  const write = (mutate: (params: URLSearchParams) => void, how: "push" | "replace") => {
    const params = new URLSearchParams(searchParams.toString());
    mutate(params);
    const href = `${window.location.pathname}?${params.toString()}`;
    if (how === "push") pushUrl(href);
    else replaceUrl(href);
  };
  const openList = (nextMetric: WhoCountsMetric | null, nextWho: string, how: "push" | "replace" = "push") =>
    write((params) => {
      if (nextMetric === null) {
        params.delete("kto");
        params.delete("osoba");
      } else {
        params.set("kto", WHO_COUNTS_METRICS[nextMetric].slug);
        params.set("osoba", nextWho);
      }
    }, how);
  const selectStage = (stage: string | null) =>
    write((params) => {
      if (stage) params.set("etap", stage);
      else params.delete("etap");
      if (who === TEAM_LIST_SLUG) {
        params.delete("kto");
        params.delete("osoba");
      }
    }, "replace");
  const setMode = (next: TrendMode) =>
    write((params) => {
      if (next === "month") params.set("os", "miesiac");
      else params.delete("os");
    }, "replace");

  const signals = useMemo(
    () => rankedSignals(data.attention.data?.items ?? [], data.inFlight, data.rows),
    [data.attention.data, data.inFlight, data.rows],
  );
  const funnel = data.funnel.data;
  if (!funnel) return null;
  const verified = stageCount(funnel, "verified");
  const hired = stageCount(funnel, "hired");
  const whole = verified >= 30 ? `${((100 * hired) / verified).toLocaleString("pl-PL", { maximumFractionDigits: 1 })}%` : "—";
  const stageSignals = selected ? signals.filter((signal) => STAGE_SIGNALS[selected.stage].includes(signal.kind)) : [];
  const selectedColumn = selected?.column ? columnOf(data.inFlight?.columns ?? [], selected.column) : null;
  const range = { start: funnel.period.start.slice(0, 10), end: addDays(funnel.period.end.slice(0, 10), -1) };
  const clicked = teamMetric ? (TEAM_STAGES.find((s) => s.metric === teamMetric) ? stageCount(funnel, TEAM_STAGES.find((s) => s.metric === teamMetric)!.stage) : null) : null;
  const tabBase = "relative min-w-0 border border-b-0 px-3 pb-2.5 pt-2 text-left transition-colors first:rounded-tl-xl last:rounded-tr-xl";
  const tabState = (active: boolean) =>
    active ? "z-10 -mb-px border-border bg-card shadow-[inset_0_2px_0_hsl(var(--primary))]" : "border-transparent bg-muted/50 hover:bg-muted";

  return (
    <div className="space-y-5">
      <div>
        <div className="overflow-x-auto">
          <div role="tablist" aria-label="Etap lejka" data-tour="insights.team-lens" className="grid min-w-[52rem] grid-cols-[7.5rem_repeat(5,minmax(0,1fr))]">
            <button type="button" role="tab" aria-selected={selected === null} onClick={() => selectStage(null)} className={cn(tabBase, tabState(selected === null))}>
              <span className="block truncate text-xs font-medium text-foreground">Cały lejek</span>
              <span className="mt-0.5 block text-2xl font-semibold tabular-nums text-foreground">{whole}</span>
              <span className="mt-1 block truncate text-xs text-muted-foreground">do placementu</span>
            </button>
            {TEAM_STAGES.map((stage, i) => {
              const count = stageCount(funnel, stage.stage);
              const column = stage.column ? columnOf(data.inFlight?.columns ?? [], stage.column) : null;
              const before = data.previousFunnel ? stageCount(data.previousFunnel, stage.stage) : undefined;
              const active = selected?.stage === stage.stage;
              const stalePct = column && column.count > 0 ? (100 * column.stale_count) / column.count : 0;
              const previous = i > 0 ? stageCount(funnel, TEAM_STAGES[i - 1].stage) : 0;
              // Akceptacje są od 12.10, a przy małej próbie procent skacze: wtedy bez procentu.
              const sameWindow = stage.stage !== "acceptance" && TEAM_STAGES[i - 1]?.stage !== "acceptance";
              const conversion = i > 0 && sameWindow && previous >= 30 ? Math.round((100 * count) / previous) : null;
              return (
                <button key={stage.stage} type="button" role="tab" aria-selected={active} onClick={() => selectStage(stage.stage)} className={cn(tabBase, tabState(active))}>
                  <span className="flex items-center justify-between gap-1 text-xs">
                    <span className="truncate font-medium text-foreground">{stage.shortLabel}</span>
                    {conversion !== null ? (
                      <span className="shrink-0 tabular-nums text-muted-foreground" title="Przejście z poprzedniego etapu w tym okresie">{conversion}%</span>
                    ) : null}
                  </span>
                  <span className="mt-0.5 flex items-baseline gap-2">
                    <span className="text-2xl font-semibold tabular-nums text-foreground">{count.toLocaleString("pl-PL")}</span>
                    {stage.stage === "acceptance" ? null : <DeltaText now={count} before={before} />}
                  </span>
                  {stage.column === null ? (
                    <span className="mt-1 block truncate text-xs tabular-nums text-muted-foreground">
                      w drodze {data.inFlight ? (forecastLabel(data.inFlight.forecast) ?? "—") : "—"}
                    </span>
                  ) : column ? (
                    <>
                      <span className="mt-1.5 flex h-1.5 overflow-hidden rounded-full bg-muted-foreground/25" title={`${column.stale_count} z ${column.count} ponad ${data.inFlight?.stale_days} dni`}>
                        <span className="block bg-warning" style={{ width: `${stalePct}%` }} />
                      </span>
                      <span className="mt-1 block truncate text-xs tabular-nums text-muted-foreground">
                        stoi {column.count} · {column.stale_count} &gt; {data.inFlight?.stale_days} dni
                      </span>
                    </>
                  ) : null}
                </button>
              );
            })}
          </div>
        </div>

        <section className="space-y-3 rounded-b-xl border border-border bg-card p-4 shadow-xs">
          {selected === null ? (
            <WholeFunnelTrend mode={mode} onMode={setMode} />
          ) : (
            <div className={cn("grid grid-cols-1 gap-6", seesTeam && "lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]")}>
              <div className="min-w-0 space-y-3">
                <StageTrend stage={selected} mode={mode} onMode={setMode} />
                {selectedColumn ? (
                  <p className="text-sm text-foreground">
                    <span className="font-semibold tabular-nums">{selectedColumn.count}</span> par {selected.waits}, najstarsza od{" "}
                    <span className="tabular-nums">{selectedColumn.oldest_days ?? "—"}</span> dni.
                  </p>
                ) : null}
              </div>
              {seesTeam ? (
                <div className="min-w-0 space-y-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h3 className="text-sm font-semibold text-foreground">Kto ma ten etap w okresie</h3>
                    {stageCount(funnel, selected.stage) > 0 ? (
                      <button type="button" onClick={() => { setWithoutCredit(false); openList(selected.metric, TEAM_LIST_SLUG); }} className="text-xs font-semibold text-primary hover:underline">
                        Pokaż listę: {stageCount(funnel, selected.stage).toLocaleString("pl-PL")}
                      </button>
                    ) : null}
                  </div>
                  <PeopleBars data={data} stage={selected} onOpen={(next) => openList(selected.metric, next)} openWho={who} openMetric={metric} />
                  {stageSignals.length > 0 ? (
                    <div className="border-t border-border pt-1.5">
                      {stageSignals.map((signal) => (
                        <SignalRow key={signal.kind} signal={signal} dense />
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          )}
          <details className="border-t border-border pt-2 text-sm">
            <summary className="cursor-pointer text-xs font-semibold text-primary">Liczby tydzień po tygodniu, z trwającym tygodniem</summary>
            <div className="pt-2">
              <StageWeeksTable data={data} canOpenList={seesTeam} openMetric={teamMetric} onOpen={(next) => { setWithoutCredit(false); openList(next, TEAM_LIST_SLUG); }} />
            </div>
          </details>
          <Link href={reportHref("lejek-etapy", period)} className="block w-fit text-xs font-semibold text-primary hover:underline">
            Wszystkie etapy i odznaki Tablicy →
          </Link>
        </section>
      </div>

      {seesTeam && teamMetric ? (
        <TeamWhoCountsPanel
          subject={withoutCredit ? { kind: "unattributed" } : { kind: "team" }}
          metric={teamMetric}
          metrics={FUNNEL_METRICS}
          range={range}
          notice={
            withoutCredit ? (
              <button type="button" onClick={() => setWithoutCredit(false)} className="w-fit text-xs font-semibold text-primary hover:underline">
                ← Cały zespół
              </button>
            ) : (
              <TeamListReconcileLine metric={teamMetric} range={range} clicked={clicked} onShowUnattributed={() => setWithoutCredit(true)} />
            )
          }
          onMetricChange={(next) => { setWithoutCredit(false); openList(next, TEAM_LIST_SLUG, "replace"); }}
          onClose={() => { setWithoutCredit(false); openList(null, TEAM_LIST_SLUG); }}
        />
      ) : null}

      {data.hiddenComparison ? (
        <p className="text-xs text-muted-foreground">
          Bez porównania z 1–5 października: te dni to tygodniowe wpisy z DynaReportera, więc początek listopada zawsze wychodziłby jako spadek.
        </p>
      ) : null}
    </div>
  );
}
