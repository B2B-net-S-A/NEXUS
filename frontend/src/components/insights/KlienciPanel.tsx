"use client";

import { useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore, hasRole } from "@/store/auth";
import { ClientsRanking } from "@/components/insights/sections/ClientsRanking";
import { DLRevenueLeaderboard } from "@/components/insights/sections/DLRevenueLeaderboard";
import { HiringManagersSection } from "@/components/insights/sections/HiringManagersSection";
import { SalesOverview } from "@/components/insights/sections/SalesOverview";
import { ClientsHitRatio } from "@/components/insights/sections/ClientsHitRatio";
import { PeriodSelector, type Period } from "@/components/insights/sections/PeriodSelector";

export function KlienciPanel() {
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

  // Audyt M7 PR-01 (P0.1): ClientsRanking + DLRevenueLeaderboard pokazują
  // lifetime/active revenue i marżę per klient/DL → tylko admin (backend
  // /api/admin/clients-overview = AdminUser). HoR nie ma VIEW_FINANCE, więc
  // traci revenue — wcześniej UI + backend wpuszczały go (split-brain).
  const canSeeClientFinance = hasRole(user, "admin", "finance");
  // Hiring managers to dane operacyjne (kontakty klienta), nie finanse — HoR
  // zachowuje dostęp, spójnie z middleware /settings/hiring-managers.
  const canSeeHiringManagers = hasRole(
    user,
    "admin",
    "head_of_recruitment",
    "finance",
  );
  // R0: SalesOverview pokazuje revenue/margin/MRR — TAC bez finansów.
  const canSeeSales = hasRole(user, "admin", "finance");
  const canSeeHitRatio = hasRole(
    user,
    "admin",
    "head_of_recruitment",
    "delivery_lead",
    "tac",
    "finance",
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Klienci, Delivery Leads, sprzedaż i hiring managers — pełna perspektywa biznesowa.
        </p>
        <PeriodSelector value={period} onChange={setPeriod} />
      </div>

      {canSeeClientFinance && <ClientsRanking />}
      {canSeeClientFinance && <DLRevenueLeaderboard />}
      {canSeeSales && <SalesOverview />}
      {canSeeHiringManagers && <HiringManagersSection />}
      {canSeeHitRatio && <ClientsHitRatio period={period} />}
    </div>
  );
}
