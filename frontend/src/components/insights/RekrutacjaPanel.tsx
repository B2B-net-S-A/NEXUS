"use client";

import { useState } from "react";
import { ActivityHeatmap } from "@/components/insights/sections/ActivityHeatmap";
import { FunnelSection } from "@/components/insights/sections/FunnelSection";
import { TimeToHireSection } from "@/components/insights/sections/TimeToHireSection";
import { SLAAlertsSection } from "@/components/insights/sections/SLAAlertsSection";
import { SourcesFunnelSection } from "@/components/insights/sections/SourcesFunnelSection";
import { PeriodSelector, type Period } from "@/components/insights/sections/PeriodSelector";

export function RekrutacjaPanel() {
  const [period, setPeriod] = useState<Period>("month");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Aktywność rekruterów, pipeline, time-to-hire i źródła kandydatów.
        </p>
        <PeriodSelector value={period} onChange={setPeriod} />
      </div>

      <ActivityHeatmap period={period} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <FunnelSection />
        <TimeToHireSection />
      </div>

      <SLAAlertsSection />

      <SourcesFunnelSection />
    </div>
  );
}
