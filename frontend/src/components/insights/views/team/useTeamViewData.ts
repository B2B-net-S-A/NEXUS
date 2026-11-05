"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { insightsApi, insightsQueryKeys, type InsightsPeriodParams } from "@/lib/insights-api";
import { insightsTeamSignalsApi, insightsTeamSignalsQueryKeys } from "@/lib/insights-team-api";
import { isFairComparison } from "@/lib/insights-team-view";
import { previousComparablePeriod } from "@/lib/insights-views";

/** Dane zakładki Zespół; klucze te same co w tabeli ludzi, więc nie ma podwójnych zapytań. */
export function useTeamViewData(period: InsightsPeriodParams, seesTeam: boolean) {
  const today = useMemo(() => new Date(), []);
  const previous = useMemo(() => previousComparablePeriod(period, today), [period, today]);
  const funnel = useQuery({
    queryKey: ["insights", "recruitment", "funnel", period],
    queryFn: () => insightsApi.recruitmentFunnel(period),
  });
  const previousFunnel = useQuery({
    queryKey: ["insights", "recruitment", "funnel", previous?.params ?? null],
    queryFn: () => insightsApi.recruitmentFunnel(previous!.params as InsightsPeriodParams),
    enabled: previous !== null,
  });
  const inFlight = useQuery({
    queryKey: insightsQueryKeys.inFlight(),
    queryFn: () => insightsApi.inFlight(),
    staleTime: 60 * 1000,
  });
  const goals = useQuery({
    queryKey: insightsQueryKeys.teamGoals(),
    queryFn: () => insightsApi.teamGoals(),
    staleTime: 60 * 1000,
  });
  const people = useQuery({
    queryKey: insightsTeamSignalsQueryKeys.people(period),
    queryFn: () => insightsTeamSignalsApi.people(period),
    enabled: seesTeam,
  });
  const attention = useQuery({
    queryKey: insightsTeamSignalsQueryKeys.attention(),
    queryFn: () => insightsTeamSignalsApi.attention(),
    enabled: seesTeam,
  });

  const window = funnel.data?.period;
  const running = window ? new Date(window.start) <= today && today < new Date(window.end) : false;
  const fair = isFairComparison(running, previousFunnel.data?.period.start);

  return {
    funnel,
    goals,
    people,
    attention,
    inFlight: inFlight.data,
    previousFunnel: fair ? previousFunnel.data : undefined,
    previousLabel: fair ? previous?.label : undefined,
    hiddenComparison: !fair,
    running,
    workdays: people.data?.workdays ?? null,
    rows: people.data?.rows ?? [],
  };
}

export type TeamViewData = ReturnType<typeof useTeamViewData>;
