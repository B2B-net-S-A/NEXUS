"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { kpisApi, type MyKpiPanel } from "@/lib/api";
import {
  insightsApi,
  insightsQueryKeys,
  type InsightsPeriodParams,
} from "@/lib/insights-api";
import { myInFlightSentence } from "@/lib/insights-in-flight";
import { racesApi } from "@/lib/insights-races-api";
import { reportHref } from "@/lib/insights-reports";
import {
  insightsTeamApi,
  insightsTeamQueryKeys,
  type TeamTableResponse,
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
import { hasRole, useAuthStore } from "@/store/auth";
import { PanelRow } from "@/components/v2/kpi/KpiGoalsPanel";
import type { KpiPanelRow } from "@/components/v2/kpi/kpi-topbar-model";
import { SectionError } from "@/components/insights/sections/_shared";
import { MyWhoCountsPanel } from "@/components/insights/sections/WhoCountsPanel";
import { MyBonusPanel } from "./my-month/MyBonusPanel";
import { MyGoalsPanel } from "./my-month/MyGoalsPanel";
import { MyInFlightPanel } from "./my-month/MyInFlightPanel";
import { MyPortfolioView } from "./my-month/MyPortfolioView";
import { FunnelBars, Panel, PanelLoading, Takeaway, ViewHeader } from "./ViewKit";

const CURRENT_MONTH: InsightsPeriodParams = { period: "month", offset: 0 };

/** Zaokrąglona średnia CV zespołu albo `null` (brak średniej = brak porównania). */
export function teamAverageCv(
  average: TeamTableResponse["anchored_average"],
): number | null {
  if (!average || average.recommendations === null) return null;
  return Math.round(average.recommendations);
}
const STEP_LABELS = ["Zweryfikowani", "CV wysłane", "Rozmowy u klienta", "Zatrudnieni"];
const STEP_LABELS_WITH_ACCEPTANCE = [
  "Zweryfikowani",
  "CV wysłane",
  "Rozmowy u klienta",
  "Akceptacje",
  "Zatrudnieni",
];

/**
 * Precyzja jako wiersz celu — ten sam wygląd co cele z górnego paska.
 * „—” i brak paska, gdy nie policzono (mniej niż 5 weryfikacji): pusty pasek
 * czytałby się jak zero.
 */
export function precisionGoalRow(precision: MyKpiPanel["precision"]): KpiPanelRow {
  const value = precision.value_pct;
  const target = precision.target_pct;
  return {
    id: "precision",
    title: `Precyzja rekomendacji (${precision.window_days} dni)`,
    value: value === null ? "—" : `${Math.round(value)}%`,
    rest: target > 0 ? `/ ${target}%` : "",
    mark: value !== null && target > 0 && value >= target ? "hit" : null,
    state:
      value === null || target <= 0 ? null : value >= target ? "hit" : "behind",
    progressPct:
      value === null || target <= 0 ? null : Math.min(100, (100 * value) / target),
    expectedPct: null,
    status: null,
    description:
      value === null
        ? "Nie policzono — mniej niż 5 weryfikacji w oknie."
        : `Ze zweryfikowanych: ${precision.verified}, CV wysłane: ${precision.sent}.`,
    link: null,
  };
}

/**
 * Mój miesiąc — rekruter widzi swoje cele i osoby, Delivery Lead swój portfel
 * (22.10.2026: do tej pory DL dostawał ekran i cele rekrutera).
 */
export function MojMiesiacView() {
  const user = useAuthStore((state) => state.user);
  return hasRole(user, "delivery_lead") ? <MyPortfolioView /> : <RecruiterMonthView />;
}

/**
 * Mój miesiąc — liczby zalogowanej osoby w BIEŻĄCYM miesiącu.
 *
 * Bez paska okresu: `/api/kpis/me/panel` liczy „teraz", tą samą atrybucją
 * co wyścigi (verifier-anchored), więc liczba placementów tutaj i w wyścigu
 * jest tą samą liczbą. Porównanie z zespołem bierze lejek całej firmy.
 */
function RecruiterMonthView() {
  const meId = useAuthStore((state) => state.user?.id ?? null);
  const today = useMemo(() => new Date(), []);
  const [showWhoCounts, setShowWhoCounts] = useState(false);

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
    queryKey: insightsTeamQueryKeys.teamTableAnchored(CURRENT_MONTH),
    queryFn: () => insightsTeamApi.teamTableWithAnchoredAverage(CURRENT_MONTH),
  });
  const seniorityQuery = useQuery({
    queryKey: ["insights", "recruitment", "seniority"],
    queryFn: () => insightsApi.seniority(),
    staleTime: 5 * 60 * 1000,
  });
  // Ta sama odpowiedź co panel „Moje osoby w drodze” (jeden klucz cache).
  const inFlightQuery = useQuery({
    queryKey: insightsQueryKeys.inFlightMe("mine"),
    queryFn: () => insightsApi.inFlightMe("mine"),
    staleTime: 60 * 1000,
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
  // Pierwsza pozycja listy to NIE kolejność nagrodowa: przy remisie na 1.
  // miejscu lidera wskaże admin, a lider kwartału jest wykluczony z nagrody.
  // Nie ogłaszamy wtedy nikogo „prowadzącym” (audyt 24.09.2026).
  const raceLeaderTie = (placementsRace?.leader_tie_user_ids ?? []).length > 0;
  const leader = raceLeaderTie
    ? null
    : (placementsRace?.qualified_leader ??
      raceRanking.find((e) => !e.excluded) ??
      null);

  // Średnia zespołu TĄ SAMĄ atrybucją co moja liczba (kredyt pierwszego
  // weryfikatora, jak `/api/kpis/me/panel`). Wiersze tabeli liczą „kto
  // kliknął" (`first_moved_by`) — porównanie z nimi mieszało atrybucje
  // (runda 6 audytu).
  const teamAvgCv = teamAverageCv(teamQuery.data?.anchored_average);

  // Lejek z akceptacjami (22.10.2026). Porównanie z zespołem bierze
  // akceptacje tylko wtedy, gdy lejek firmy liczy je przez cały miesiąc —
  // przed 12.10.2026 nikt ich nie odnotowywał, więc iloraz byłby fałszywy.
  const mySteps = panel
    ? buildSteps(STEP_LABELS_WITH_ACCEPTANCE, [
        panel.weryfikacje.month,
        panel.rekomendacje.month,
        panel.interview_month,
        panel.akceptacje_month,
        panel.placementy_month,
      ])
    : [];
  const stage = (code: string) =>
    funnelQuery.data?.stages.find((s) => s.stage === code) ?? null;
  const stageCount = (code: string) => stage(code)?.count ?? 0;
  const acceptanceComparable = stage("acceptance")?.counted_from == null;
  const myStepsForTeam =
    acceptanceComparable || !panel
      ? mySteps
      : buildSteps(STEP_LABELS, [
          panel.weryfikacje.month,
          panel.rekomendacje.month,
          panel.interview_month,
          panel.placementy_month,
        ]);
  const teamSteps = funnelQuery.data
    ? acceptanceComparable
      ? buildSteps(STEP_LABELS_WITH_ACCEPTANCE, [
          stageCount("verified"),
          stageCount("cv_sent"),
          stageCount("client_interview"),
          stageCount("acceptance"),
          stageCount("hired"),
        ])
      : buildSteps(STEP_LABELS, [
          stageCount("verified"),
          stageCount("cv_sent"),
          // Rozmowy u klienta — ta sama definicja co `/api/kpis/me/panel`
          // (`interview_month` = `client_interview`, runda 7).
          stageCount("client_interview"),
          stageCount("hired"),
        ])
    : [];
  const funnelSentence =
    (teamSteps.length ? gapSentence(myStepsForTeam, teamSteps) : null) ??
    weakestStepSentence(mySteps);
  const inFlightSentence = inFlightQuery.data
    ? myInFlightSentence(inFlightQuery.data.columns)
    : null;
  const recommendationsEntry =
    racesQuery.data?.recommendations?.ranking.find((e) => e.user_id === meId) ?? null;

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
          raceLeader:
            !raceLeaderTie &&
            placementsRace?.qualified_leader?.user_id === meId &&
            meId !== null,
          raceLeaderTie,
          raceExcluded: myRaceEntry?.excluded ?? false,
          leaderPlacements: leader?.metric_value ?? null,
          leaderName: leader && leader.user_id !== meId ? leader.name : null,
          verificationsToday: panel.weryfikacje.day,
          verificationsDailyTarget: panel.target_verifications_daily,
        })}
        {inFlightSentence ? ` ${inFlightSentence}` : null}
      </p>

      <MyGoalsPanel
        extra={<PanelRow row={precisionGoalRow(panel.precision)} />}
        footnote={`W miesiącu: ${panel.weryfikacje.month} weryfikacji, ${panel.rekomendacje.month} CV wysłanych${
          teamAvgCv !== null ? ` (średnia zespołu: ${teamAvgCv})` : ""
        }.`}
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <MyInFlightPanel scope="mine" />
        <MyBonusPanel />
      </div>

      <section className="rounded-xl border border-border bg-card shadow-xs">
        <button
          type="button"
          aria-expanded={showWhoCounts}
          onClick={() => setShowWhoCounts((v) => !v)}
          className="flex min-h-11 w-full items-center justify-between gap-3 px-4 text-left text-sm font-semibold text-foreground"
        >
          Kto się liczy do celów — osoby za liczbami
          <span className="text-primary">{showWhoCounts ? "Zwiń ▴" : "Pokaż ▾"}</span>
        </button>
        {showWhoCounts ? (
          <div className="border-t border-border p-4">
            <MyWhoCountsPanel />
          </div>
        ) : null}
      </section>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Panel title="Mój lejek w tym miesiącu" hint="pierwsze wejście na etap">
          <FunnelBars steps={mySteps} />
          {funnelSentence ? <Takeaway>{funnelSentence}</Takeaway> : null}
        </Panel>

        <Panel
          title="Wyścig placementów"
          hint={placementsRace?.prize.name ?? undefined}
        >
          {/* Runda 8 (R8-N14-2): zdanie o pustym wyścigu tylko po udanym
              odczycie — awaria i wczytywanie to nie „nikt się nie kwalifikuje”. */}
          {racesQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Wczytuję wyścig…</p>
          ) : racesQuery.isError && !racesQuery.data ? (
            <SectionError
              label="Wyścig placementów"
              error={racesQuery.error}
              onRetry={() => void racesQuery.refetch()}
            />
          ) : raceRanking.length === 0 ? (
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
          {recommendationsEntry ? (
            <p className="border-t border-border pt-3 text-sm text-muted-foreground">
              Wyścig rekomendacji:{" "}
              <strong className="text-foreground">
                {recommendationsEntry.rank}. miejsce, {recommendationsEntry.metric_value} rek.
              </strong>
              {recommendationsEntry.qualified === false
                ? " — warunek udziału jeszcze niespełniony."
                : "."}
            </p>
          ) : null}
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
          ) : league?.me ? (
            // Na liście, ale bez miejsca w klasyfikacji nagrodowej (próg
            // placementów niespełniony) — numer z pozycji listy ogłaszał tu
            // „1. miejsce” komuś, kto nagrody nie dostanie (audyt 25.09.2026).
            <p className="border-t border-border pt-3 text-sm text-muted-foreground">
              Liga Mistrzów (kwartał):{" "}
              <strong className="text-foreground">
                {league.me.metric_value ?? 0} pkt, bez miejsca w klasyfikacji
              </strong>{" "}
              — warunek udziału nie jest jeszcze spełniony.
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
