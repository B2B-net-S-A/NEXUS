"use client";

import { useQuery } from "@tanstack/react-query";

import { PanelRow } from "@/components/v2/kpi/KpiGoalsPanel";
import { buildKpiTopbarModel } from "@/components/v2/kpi/kpi-topbar-model";
import { insightsApi, insightsQueryKeys } from "@/lib/insights-api";
import { forecastLabel, monthForecast } from "@/lib/insights-in-flight";
import { countPl } from "@/lib/plural-pl";
import { SectionError } from "@/components/insights/sections/_shared";

import { Panel, PanelLoading } from "../ViewKit";

/**
 * „Cele zespołu” (22.10.2026): te same sumy celów i pracy, które Head of
 * Recruitment ma w liczniku górnego paska — teraz dla każdego, kto widzi
 * Insights (bez osób). Obok prognoza miesiąca: placementy + szacunek
 * z otwartych akceptacji. Cele liczą „teraz” (dzień, tydzień, miesiąc),
 * niezależnie od paska okresu.
 */
export function TeamGoalsPanel() {
  const goals = useQuery({
    queryKey: insightsQueryKeys.teamGoals(),
    queryFn: () => insightsApi.teamGoals(),
    staleTime: 60 * 1000,
  });
  const inFlight = useQuery({
    queryKey: insightsQueryKeys.inFlight(),
    queryFn: () => insightsApi.inFlight(),
    staleTime: 60 * 1000,
  });
  if (goals.isPending) return <PanelLoading />;
  if (goals.isError) {
    return (
      <SectionError label="Cele zespołu" error={goals.error} onRetry={() => void goals.refetch()} />
    );
  }
  const model = buildKpiTopbarModel([], goals.data);
  const rows = model?.groups.flatMap((group) => group.rows) ?? [];
  if (rows.length === 0) return null;
  const monthPlacements = goals.data.goals.find(
    (goal) => goal.goal_id === "team_monthly_placements",
  );
  const forecast = inFlight.data ? forecastLabel(inFlight.data.forecast) : null;
  const total =
    inFlight.data && monthPlacements?.current != null
      ? monthForecast(monthPlacements.current, inFlight.data.forecast)
      : null;

  return (
    <Panel title="Cele zespołu" hint="teraz — suma celów osób, bez nazwisk">
      <div className="grid grid-cols-1 gap-x-6 gap-y-5 sm:grid-cols-2 xl:grid-cols-[repeat(3,minmax(0,1fr))_minmax(0,0.9fr)]">
        {rows.map((row) => (
          <PanelRow key={row.id} row={row} />
        ))}
        {monthPlacements && monthPlacements.current !== null ? (
          <div className="rounded-lg bg-foreground p-3 text-background">
            <p className="text-xs font-semibold uppercase tracking-wide opacity-80">
              Prognoza miesiąca
            </p>
            <p className="text-2xl font-bold tabular-nums">
              {total ?? monthPlacements.current}
            </p>
            <p className="text-xs opacity-80">
              {forecast
                ? `${countPl(monthPlacements.current, "placement", "placementy", "placementów")} + ${forecast} z otwartych akceptacji`
                : "placementy w miesiącu; szacunek z akceptacji po 10 rozstrzygnięciach"}
            </p>
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
