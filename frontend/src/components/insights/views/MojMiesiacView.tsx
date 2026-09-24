"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { kpisApi } from "@/lib/api";
import { insightsApi, type InsightsPeriodParams } from "@/lib/insights-api";
import { racesApi } from "@/lib/insights-races-api";
import { reportHref } from "@/lib/insights-reports";
import {
  insightsTeamApi,
  insightsTeamQueryKeys,
} from "@/lib/insights-team-api";
import {
  buildSteps,
  currentMonthCaption,
  gapSentence,
  myMonthSentence,
  placementsPl,
  weakestStepSentence,
} from "@/lib/insights-views";
import { resolveViewState, isBlockingViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";
import { SectionError } from "@/components/insights/sections/_shared";
import {
  FunnelBars,
  Panel,
  PanelLoading,
  Takeaway,
  Tile,
  TileRow,
  ViewHeader,
} from "./ViewKit";

const CURRENT_MONTH: InsightsPeriodParams = { period: "month", offset: 0 };
const STEP_LABELS = ["Zweryfikowani", "CV wysłane", "Rozmowy", "Zatrudnieni"];

/**
 * Mój miesiąc — liczby zalogowanej osoby w BIEŻĄCYM miesiącu.
 *
 * Bez paska okresu: `/api/kpis/me/panel` liczy „teraz", tą samą atrybucją
 * co wyścigi (verifier-anchored), więc liczba placementów tutaj i w wyścigu
 * jest tą samą liczbą. Porównanie z zespołem bierze lejek całej firmy.
 */
export function MojMiesiacView() {
  const meId = useAuthStore((state) => state.user?.id ?? null);
  const today = useMemo(() => new Date(), []);

  const panelQuery = useQuery({
    queryKey: ["insights", "me", "panel"],
    queryFn: () => kpisApi.myPanel().then((r) => r.data),
    staleTime: 60 * 1000,
  });
  const racesQuery = useQuery({
    queryKey: ["insights", "monthly-races", "current"],
    queryFn: () => racesApi.monthlyRaces(),
    staleTime: 5 * 60 * 1000,
  });
  const leagueQuery = useQuery({
    queryKey: ["insights", "me", "position", "quarterly_champions_recruiter"],
    queryFn: () => racesApi.myPosition("quarterly_champions_recruiter"),
    staleTime: 5 * 60 * 1000,
  });
  const funnelQuery = useQuery({
    queryKey: ["insights", "recruitment", "funnel", CURRENT_MONTH],
    queryFn: () => insightsApi.recruitmentFunnel(CURRENT_MONTH),
  });
  const teamQuery = useQuery({
    queryKey: insightsTeamQueryKeys.teamTable(CURRENT_MONTH),
    queryFn: () => insightsTeamApi.teamTable(CURRENT_MONTH),
  });
  const seniorityQuery = useQuery({
    queryKey: ["insights", "recruitment", "seniority"],
    queryFn: () => insightsApi.seniority(),
    staleTime: 5 * 60 * 1000,
  });

  const panel = panelQuery.data;
  const viewState = resolveViewState({
    isLoading: panelQuery.isPending,
    isSuccess: panelQuery.isSuccess,
    isError: panelQuery.isError,
    error: panelQuery.error,
  });

  const placementsRace = racesQuery.data?.placements;
  const raceRanking = placementsRace?.ranking ?? [];
  const myRaceEntry = raceRanking.find((e) => e.user_id === meId) ?? null;
  const leader = placementsRace?.qualified_leader ?? raceRanking[0] ?? null;

  const teamRows = teamQuery.data?.rows ?? [];
  const activeTeam = teamRows.filter((r) => r.recommendations > 0);
  const teamAvgCv = activeTeam.length
    ? Math.round(
        activeTeam.reduce((sum, r) => sum + r.recommendations, 0) /
          activeTeam.length,
      )
    : null;

  const mySteps = panel
    ? buildSteps(STEP_LABELS, [
        panel.weryfikacje.month,
        panel.rekomendacje.month,
        panel.interview_month,
        panel.placementy_month,
      ])
    : [];
  const stageCount = (stage: string) =>
    funnelQuery.data?.stages.find((s) => s.stage === stage)?.count ?? 0;
  const teamSteps = funnelQuery.data
    ? buildSteps(STEP_LABELS, [
        stageCount("verified"),
        stageCount("cv_sent"),
        stageCount("interview"),
        stageCount("hired"),
      ])
    : [];
  const funnelSentence =
    (teamSteps.length ? gapSentence(mySteps, teamSteps) : null) ??
    weakestStepSentence(mySteps);

  const mySeniority =
    seniorityQuery.data?.entries.find((e) => e.user_id === meId) ?? null;
  const league = leagueQuery.data;
  const podiumThird = league?.context.find((e) => e.rank === 3) ?? null;

  if (viewState === "loading") return <PanelLoading />;
  if (isBlockingViewState(viewState) || !panel) {
    return (
      <SectionError
        label="Mój miesiąc"
        error={panelQuery.error}
        onRetry={() => void panelQuery.refetch()}
      />
    );
  }

  const precision = panel.precision.value_pct;
  return (
    <div className="space-y-6">
      <ViewHeader
        question="Jak idzie mi ten miesiąc?"
        lede={currentMonthCaption(today)}
      />
      <p className="max-w-4xl text-base leading-relaxed text-foreground">
        {myMonthSentence({
          placements: panel.placementy_month,
          placementsTarget: panel.target_placements_monthly,
          raceRank: myRaceEntry?.rank ?? null,
          leaderPlacements: leader?.metric_value ?? null,
          leaderName: leader && leader.user_id !== meId ? leader.name : null,
          verificationsToday: panel.weryfikacje.day,
          verificationsDailyTarget: panel.target_verifications_daily,
        })}
      </p>

      <TileRow>
        <Tile
          label="Placementy w miesiącu"
          value={String(panel.placementy_month)}
          reference={`cel: ${panel.target_placements_monthly}`}
          delta={
            panel.placementy_month >= panel.target_placements_monthly
              ? { text: "Cel osiągnięty", tone: "good" }
              : {
                  text: `Brakuje ${panel.target_placements_monthly - panel.placementy_month}`,
                  tone: "bad",
                }
          }
        />
        <Tile
          label="Weryfikacje dziś"
          value={String(panel.weryfikacje.day)}
          reference={`cel: ${panel.target_verifications_daily}`}
          progress={
            panel.target_verifications_daily
              ? (100 * panel.weryfikacje.day) / panel.target_verifications_daily
              : null
          }
          note={`W miesiącu: ${panel.weryfikacje.month}`}
        />
        <Tile
          label="CV wysłane do klienta"
          value={String(panel.rekomendacje.month)}
          reference={teamAvgCv !== null ? `średnia zespołu: ${teamAvgCv}` : null}
          delta={
            teamAvgCv === null
              ? null
              : panel.rekomendacje.month >= teamAvgCv
                ? { text: "Na poziomie zespołu lub wyżej", tone: "good" }
                : { text: "Poniżej średniej zespołu", tone: "bad" }
          }
        />
        <Tile
          label={`Precyzja rekomendacji (${panel.precision.window_days} dni)`}
          value={precision === null ? "—" : `${Math.round(precision)}%`}
          reference={`cel: ${panel.precision.target_pct}%`}
          progress={
            precision === null || !panel.precision.target_pct
              ? null
              : (100 * precision) / panel.precision.target_pct
          }
          note={
            precision === null
              ? "Nie policzono — mniej niż 5 weryfikacji w oknie."
              : null
          }
        />
      </TileRow>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Panel title="Mój lejek w tym miesiącu" hint="pierwsze wejście na etap">
          <FunnelBars steps={mySteps} />
          {funnelSentence ? <Takeaway>{funnelSentence}</Takeaway> : null}
        </Panel>

        <Panel
          title="Wyścig placementów"
          hint={placementsRace?.prize.name ?? undefined}
        >
          {raceRanking.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nikt nie ma jeszcze wymaganej liczby placementów w tym miesiącu.
            </p>
          ) : (
            <ol className="space-y-1">
              {raceRanking
                .filter((e, i) => i < 5 || e.user_id === meId)
                .map((entry) => (
                  <li
                    key={entry.user_id}
                    aria-current={entry.user_id === meId ? "true" : undefined}
                    className={cn(
                      "grid grid-cols-[2rem_minmax(0,1fr)_3rem] items-center rounded-md px-2 py-1.5 text-sm",
                      entry.user_id === meId
                        ? "bg-primary/10 font-semibold"
                        : "border-b border-border/60",
                    )}
                  >
                    <span className="tabular-nums text-muted-foreground">
                      {entry.rank}.
                    </span>
                    <span className="truncate text-foreground">
                      {entry.user_id === meId ? "Ty" : entry.name}
                      {entry.excluded ? (
                        <span className="ml-1 text-xs font-normal text-muted-foreground">
                          (lider kwartału, bez nagrody)
                        </span>
                      ) : null}
                    </span>
                    <span className="text-right font-semibold tabular-nums">
                      {entry.metric_value}
                    </span>
                  </li>
                ))}
            </ol>
          )}
          {league?.rank ? (
            <p className="border-t border-border pt-3 text-sm text-muted-foreground">
              Liga Mistrzów (kwartał):{" "}
              <strong className="text-foreground">
                {league.rank}. miejsce, {league.me?.metric_value ?? 0} pkt
              </strong>
              {podiumThird && league.rank > 3 && league.me
                ? ` — do podium brakuje ${Math.max(podiumThird.metric_value - league.me.metric_value, 0)} pkt.`
                : "."}
            </p>
          ) : null}
          <Link
            href="/insights?tab=rywalizacja"
            className="text-sm font-semibold text-primary hover:underline"
          >
            Cała rywalizacja →
          </Link>
        </Panel>
      </div>

      {mySeniority ? (
        <section className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-xl border border-border bg-card px-4 py-3 shadow-xs">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Ścieżka rozwoju
            </p>
            <p className="text-sm font-semibold capitalize text-foreground">
              {mySeniority.level}
            </p>
          </div>
          <div className="min-w-[12rem] flex-1 space-y-1">
            {mySeniority.progress_pct !== null ? (
              <div className="h-2 rounded-full bg-muted">
                <div
                  className="h-2 rounded-full bg-primary"
                  style={{
                    width: `${Math.max(0, Math.min(mySeniority.progress_pct, 100))}%`,
                  }}
                />
              </div>
            ) : null}
            <p className="text-sm text-muted-foreground">
              {mySeniority.placements_to_next_level === null
                ? "Najwyższy poziom."
                : `Do awansu brakuje ${mySeniority.placements_to_next_level} ${placementsPl(mySeniority.placements_to_next_level)}.`}
            </p>
          </div>
          <Link
            href={reportHref("sciezka")}
            className="text-sm font-semibold text-primary hover:underline"
          >
            Zasady i historia →
          </Link>
        </section>
      ) : null}
    </div>
  );
}
