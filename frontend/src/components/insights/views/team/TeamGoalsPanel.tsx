"use client";

import { useQuery } from "@tanstack/react-query";

import { PanelRow } from "@/components/v2/kpi/KpiGoalsPanel";
import { buildKpiTopbarModel } from "@/components/v2/kpi/kpi-topbar-model";
import { insightsApi, insightsQueryKeys } from "@/lib/insights-api";
import { companyPlacementsNote, forecastLabel, monthForecast } from "@/lib/insights-in-flight";
import { countPl } from "@/lib/plural-pl";
import { SectionError } from "@/components/insights/sections/_shared";

import { Panel, PanelLoading } from "../ViewKit";

/**
 * „Cele zespołu” (22.10.2026): te same sumy celów i pracy, które Head of
 * Recruitment ma w liczniku górnego paska — teraz dla każdego, kto widzi
 * Insights (bez osób). Obok prognoza miesiąca: placementy całej firmy + szacunek
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
  const monthPlacements = goals.data.goals.find(
    (goal) => goal.goal_id === "team_monthly_placements",
  );
  // Cel sumuje tylko osoby z tym celem; prognoza i dopisek liczą całą firmę
  // (ta sama liczba co lejek), bo akceptacje „w drodze” też są całej firmy.
  const company = goals.data.company_month_placements;
  const rows = (model?.groups.flatMap((group) => group.rows) ?? []).map((row) =>
    row.id === "team_monthly_placements" && monthPlacements?.current != null
      ? {
          ...row,
          description: [row.description, companyPlacementsNote(monthPlacements.current, company)]
            .filter(Boolean)
            .join(". "),
        }
      : row,
  );
  if (rows.length === 0) return null;
  const forecast = inFlight.data ? forecastLabel(inFlight.data.forecast) : null;
  const total = inFlight.data ? monthForecast(company, inFlight.data.forecast) : null;

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
            <p className="text-2xl font-bold tabular-nums">{total ?? company}</p>
            <p className="text-xs opacity-80">
              {forecast
                ? `${countPl(company, "placement", "placementy", "placementów")} w firmie + ${forecast} z otwartych akceptacji`
                : "placementy firmy w miesiącu; szacunek z akceptacji po 10 rozstrzygnięciach"}
            </p>
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
