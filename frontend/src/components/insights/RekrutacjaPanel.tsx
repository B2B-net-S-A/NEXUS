"use client";

import { useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore, hasRole } from "@/store/auth";
import { ActivityHeatmap } from "@/components/insights/sections/ActivityHeatmap";
import { FunnelSection } from "@/components/insights/sections/FunnelSection";
import { TimeToHireSection } from "@/components/insights/sections/TimeToHireSection";
import { SLAAlertsSection } from "@/components/insights/sections/SLAAlertsSection";
import { SourcesFunnelSection } from "@/components/insights/sections/SourcesFunnelSection";
import { PeriodSelector, type Period } from "@/components/insights/sections/PeriodSelector";

export function RekrutacjaPanel() {
  const user = useAuthStore((s) => s.user);
  // Plan PR 5 (§Okresy): URL jest jedynym źródłem prawdy okresu —
  // back/forward odtwarza wybór, link można udostępnić.
  const router = useRouter();
  const searchParams = useSearchParams();
  const rawPeriod = searchParams.get("period");
  const period: Period = (
    ["today", "week", "month", "quarter"].includes(rawPeriod ?? "")
      ? rawPeriod
      : "month"
  ) as Period;
  const setPeriod = useCallback(
    (next: Period) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("period", next);
      router.push(`/insights?${params.toString()}`);
    },
    [router, searchParams]
  );
  // R0 (plan analytics 2026-07-16): heatmapa bazuje na imiennym leaderboardzie
  // (/api/activities/leaderboard, VIEW_RECRUITMENT_RANKING) — viewer `user`
  // widzi wyłącznie agregaty (lejek, TTH, źródła), bez rankingu osób.
  const canSeeRanking = hasRole(
    user,
    "admin",
    "head_of_recruitment",
    "delivery_lead",
    "tac",
    "recruiter",
    "sourcer"
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Aktywność rekruterów, pipeline, time-to-hire i źródła kandydatów.
        </p>
        <PeriodSelector value={period} onChange={setPeriod} />
      </div>

      {canSeeRanking && <ActivityHeatmap period={period} />}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <FunnelSection />
        <TimeToHireSection />
      </div>

      <SLAAlertsSection />

      <SourcesFunnelSection />
    </div>
  );
}
