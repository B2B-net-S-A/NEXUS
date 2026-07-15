"use client";

import {
  canViewHiringManagerAnalytics,
  hasAnalyticsCapability,
  useAuthStore,
} from "@/store/auth";
import { ClientsRanking } from "@/components/insights/sections/ClientsRanking";
import { HiringManagersSection } from "@/components/insights/sections/HiringManagersSection";
import { ClientsHitRatio } from "@/components/insights/sections/ClientsHitRatio";
import { DeliveryLeadPerformanceSection } from "@/components/insights/sections/DeliveryLeadPerformanceSection";
import { FinanceAnalyticsSection } from "@/components/insights/sections/FinanceAnalyticsSection";
import { PeriodSelector } from "@/components/insights/sections/PeriodSelector";
import { useInsightsPeriod } from "@/components/insights/useInsightsPeriod";

export function KlienciPanel() {
  const user = useAuthStore((s) => s.user);
  const [period, setPeriod] = useInsightsPeriod("month");

  const canSeeClientOperations = hasAnalyticsCapability(user, "view_client_operations");
  const canSeeFinance = hasAnalyticsCapability(user, "view_finance");
  const canSeeHiringManagers = canViewHiringManagerAnalytics(user);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Klienci, Delivery Leads, sprzedaż i hiring managers — pełna perspektywa biznesowa.
        </p>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Okres hit ratio</span>
          <PeriodSelector value={period} onChange={setPeriod} />
        </div>
      </div>

      {canSeeFinance && <ClientsRanking />}
      {canSeeClientOperations && <DeliveryLeadPerformanceSection period={period} />}
      {canSeeFinance && <FinanceAnalyticsSection period={period} />}
      {canSeeHiringManagers && <HiringManagersSection />}
      {canSeeClientOperations && <ClientsHitRatio period={period} />}
    </div>
  );
}
