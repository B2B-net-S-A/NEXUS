"use client";

import { useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore, hasRole } from "@/store/auth";
import { ClientsRanking } from "@/components/insights/sections/ClientsRanking";
import { DLRevenueLeaderboard } from "@/components/insights/sections/DLRevenueLeaderboard";
import { HiringManagersSection } from "@/components/insights/sections/HiringManagersSection";
import { ClientsHitRatio } from "@/components/insights/sections/ClientsHitRatio";
import {
  PeriodSelector,
  type Period,
} from "@/components/insights/sections/PeriodSelector";

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
    [router, searchParams],
  );

  // D7 (Artur, 2026-08-31): CZTERY bramki rolowe zdjęte —
  // canSeeClientFinance / canSeeHiringManagers / canSeeSales / canSeeHitRatio.
  // To były gołe wywołania `hasRole` w ciele panelu, czyli lustro ról, którego
  // NIE znajdzie sweep szukający `RequireRole` ani tablic `roles:`. Jeśli
  // kiedyś wrócisz do zawężania — zacznij od decyzji §0 D7, nie stąd.

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Klienci, Delivery Leads i hiring managers — pełna perspektywa
          biznesowa.
        </p>
        <PeriodSelector value={period} onChange={setPeriod} />
      </div>

      <ClientsRanking />
      <DLRevenueLeaderboard />
      <HiringManagersSection />
      <ClientsHitRatio period={period} />
    </div>
  );
}
