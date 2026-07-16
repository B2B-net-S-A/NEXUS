"use client";

import { useState } from "react";
import { useAuthStore, hasRole } from "@/store/auth";
import { ClientsRanking } from "@/components/insights/sections/ClientsRanking";
import { DLRevenueLeaderboard } from "@/components/insights/sections/DLRevenueLeaderboard";
import { HiringManagersSection } from "@/components/insights/sections/HiringManagersSection";
import { SalesOverview } from "@/components/insights/sections/SalesOverview";
import { ClientsHitRatio } from "@/components/insights/sections/ClientsHitRatio";
import { PeriodSelector, type Period } from "@/components/insights/sections/PeriodSelector";

export function KlienciPanel() {
  const user = useAuthStore((s) => s.user);
  const [period, setPeriod] = useState<Period>("month");

  const canSeeAdminClients = hasRole(user, "admin", "head_of_recruitment");
  // R0: SalesOverview pokazuje revenue/margin/MRR — TAC bez finansów.
  const canSeeSales = hasRole(user, "admin", "delivery_lead");
  const canSeeHitRatio = hasRole(user, "admin", "head_of_recruitment", "delivery_lead", "tac");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Klienci, Delivery Leads, sprzedaż i hiring managers — pełna perspektywa biznesowa.
        </p>
        <PeriodSelector value={period} onChange={setPeriod} />
      </div>

      {canSeeAdminClients && <ClientsRanking />}
      {canSeeAdminClients && <DLRevenueLeaderboard />}
      {canSeeSales && <SalesOverview />}
      {canSeeAdminClients && <HiringManagersSection />}
      {canSeeHitRatio && <ClientsHitRatio period={period} />}
    </div>
  );
}
