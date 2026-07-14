"use client";

import { BoardKPI } from "@/components/insights/sections/BoardKPI";
import { TendersSection } from "@/components/insights/sections/TendersSection";
import { InviteLinksSection } from "@/components/insights/sections/InviteLinksSection";
import { ChampionsSection } from "@/components/insights/sections/ChampionsSection";
import { PeriodSelector } from "@/components/insights/sections/PeriodSelector";
import { hasAnalyticsCapability, useAuthStore } from "@/store/auth";
import { useInsightsPeriod } from "@/components/insights/useInsightsPeriod";

export function ZarzadPanel() {
  const user = useAuthStore((state) => state.user);
  const canViewFinance = hasAnalyticsCapability(user, "view_finance");
  const canViewTenders = hasAnalyticsCapability(user, "view_tenders");
  const canViewTeam = hasAnalyticsCapability(user, "view_recruitment_team");
  const [period, setPeriod] = useInsightsPeriod("quarter");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Executive dashboard — YTD KPI, trendy, przetargi, linki aplikacyjne, Liga Mistrzów.
        </p>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">
            Okres przetargów i linków
          </span>
          <PeriodSelector value={period} onChange={setPeriod} />
        </div>
      </div>

      {canViewFinance && <BoardKPI period={period} />}

      <div className="grid grid-cols-1 gap-6">
        {canViewTeam && <ChampionsSection />}
        {canViewTenders && <TendersSection period={period} />}
        {canViewFinance && <InviteLinksSection period={period} />}
      </div>
    </div>
  );
}
