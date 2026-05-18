"use client";

import { useState } from "react";
import { BoardKPI } from "@/components/insights/sections/BoardKPI";
import { TendersSection } from "@/components/insights/sections/TendersSection";
import { InviteLinksSection } from "@/components/insights/sections/InviteLinksSection";
import { ChampionsSection } from "@/components/insights/sections/ChampionsSection";
import { PeriodSelector, type Period } from "@/components/insights/sections/PeriodSelector";

export function ZarzadPanel() {
  const [period, setPeriod] = useState<Period>("quarter");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Executive dashboard — YTD KPI, trendy, przetargi, linki aplikacyjne, Liga Mistrzów.
        </p>
        <PeriodSelector value={period} onChange={setPeriod} />
      </div>

      <BoardKPI />

      <div className="grid grid-cols-1 gap-6">
        <ChampionsSection />
        <TendersSection period={period} />
        <InviteLinksSection period={period} />
      </div>
    </div>
  );
}
