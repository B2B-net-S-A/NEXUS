"use client";

import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { PeriodPicker } from "@/components/insights/PeriodPicker";
import { HiringManagersSection } from "@/components/insights/sections/HiringManagersSection";
import { InsightsClientsHitRatio } from "@/components/insights/sections/InsightsClientsHitRatio";
import { InsightsClientsRanking } from "@/components/insights/sections/InsightsClientsRanking";
import { InsightsDeliveryLeads } from "@/components/insights/sections/InsightsDeliveryLeads";
import { InsightsPlacementsByClient } from "@/components/insights/sections/InsightsPlacementsByClient";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsPeriodKind,
  type InsightsPeriodParams,
} from "@/lib/insights-api";

const KINDS: InsightsPeriodKind[] = ["week", "month", "quarter", "year"];

export function KlienciPanel() {
  // URL jest jedynym źródłem prawdy okresu — back/forward odtwarza wybór,
  // a link da się udostępnić. Ten sam wzorzec co w `RekrutacjaPanel`; dawny
  // `PeriodSelector` oferował okna KROCZĄCE („Ostatnie 30 dni"), podczas gdy
  // `/api/insights/*` liczy KALENDARZOWO — etykieta obiecywała co innego niż
  // liczby pod nią.
  const router = useRouter();
  const searchParams = useSearchParams();

  const rawKind = searchParams.get("period");
  const rawOffset = Number.parseInt(searchParams.get("offset") ?? "0", 10);

  const period: InsightsPeriodParams = useMemo(
    () => ({
      period: (KINDS.includes(rawKind as InsightsPeriodKind)
        ? rawKind
        : "month") as InsightsPeriodKind,
      offset: Number.isFinite(rawOffset) ? rawOffset : 0,
    }),
    [rawKind, rawOffset],
  );

  const setPeriod = useCallback(
    (next: InsightsPeriodParams) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("period", next.period);
      params.set("offset", String(next.offset ?? 0));
      router.push(`/insights?${params.toString()}`, { scroll: false });
    },
    [router, searchParams],
  );

  // Etykieta okna pochodzi z SERWERA, nie z arytmetyki we froncie — inaczej
  // dwie strony liczyłyby granice miesiąca osobno i rozjechałyby się przy DST.
  // Klucz jest ten sam co w sekcji rankingu, więc react-query deduplikuje
  // zapytanie zamiast wołać endpoint drugi raz.
  const { data: ranking } = useQuery({
    queryKey: insightsQueryKeys.clientsRanking(period),
    queryFn: () => insightsBoardApi.clientsRanking(period),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Klienci, Delivery Leadzi i hiring managerowie — pełna perspektywa
          biznesowa.
        </p>
        <PeriodPicker
          value={period}
          onChange={setPeriod}
          resolved={ranking?.period ?? null}
        />
      </div>

      {/* D7 (Artur, 2026-08-31): CZTERY bramki rolowe zdjęte —
          canSeeClientFinance / canSeeHiringManagers / canSeeSales /
          canSeeHitRatio. To były gołe wywołania `hasRole` w ciele panelu, czyli
          lustro ról, którego NIE znajdzie sweep szukający `RequireRole` ani
          tablic `roles:`. Jeśli kiedyś wrócisz do zawężania — zacznij od
          decyzji §0 D7, nie stąd. */}

      <InsightsClientsRanking period={period} />
      <InsightsDeliveryLeads period={period} />
      <InsightsPlacementsByClient period={period} />
      <InsightsClientsHitRatio period={period} />

      {/* Bez odpowiednika w `/api/insights/*` — zostaje na `/api/reports/
          hiring-managers`, który ma własny, węższy guard. Sekcja renderuje
          własny komunikat, gdy rola nie ma dostępu; nie chowamy jej z ekranu,
          bo ukryta sekcja przy otwartym API to split-brain, nie zabezpieczenie. */}
      <HiringManagersSection />
    </div>
  );
}
