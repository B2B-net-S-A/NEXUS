"use client";

import { ActivityHeatmap } from "@/components/insights/sections/ActivityHeatmap";
import { FunnelSection } from "@/components/insights/sections/FunnelSection";
import { TimeToHireSection } from "@/components/insights/sections/TimeToHireSection";
import { SLAAlertsSection } from "@/components/insights/sections/SLAAlertsSection";
import { SourcesFunnelSection } from "@/components/insights/sections/SourcesFunnelSection";
import { PeriodSelector } from "@/components/insights/sections/PeriodSelector";
import { hasAnalyticsCapability, useAuthStore } from "@/store/auth";
import { useInsightsPeriod } from "@/components/insights/useInsightsPeriod";
import { PersonalKpiCoach } from "@/components/v2/kpi/MojeKpiPanel";
import { TeamKpiCoachSummary } from "@/components/v2/kpi/TeamKpiPanel";

export function RekrutacjaPanel() {
  const user = useAuthStore((state) => state.user);
  const canViewTeam = hasAnalyticsCapability(user, "view_recruitment_team");
  const [period, setPeriod] = useInsightsPeriod("month");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Aktywność rekruterów, pipeline, time-to-hire i źródła kandydatów.
        </p>
        {canViewTeam && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">Okres aktywności zespołu</span>
            <PeriodSelector value={period} onChange={setPeriod} />
          </div>
        )}
      </div>

      <PersonalKpiCoach />
      {canViewTeam && <TeamKpiCoachSummary />}

      {canViewTeam && <ActivityHeatmap period={period} />}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <FunnelSection period={period} />
        {canViewTeam && <TimeToHireSection />}
      </div>

      {canViewTeam && <SLAAlertsSection />}

      <SourcesFunnelSection period={period} />
    </div>
  );
}
