"use client";

import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { PeriodPicker } from "@/components/insights/PeriodPicker";
import { ChampionsSection } from "@/components/insights/sections/ChampionsSection";
import { InsightsBoardKPI } from "@/components/insights/sections/InsightsBoardKPI";
import { InviteLinksSection } from "@/components/insights/sections/InviteLinksSection";
import { Degraded } from "@/components/insights/sections/_shared";
import type { Period } from "@/components/insights/sections/PeriodSelector";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsPeriodKind,
  type InsightsPeriodParams,
} from "@/lib/insights-api";

const KINDS: InsightsPeriodKind[] = ["week", "month", "quarter", "year"];

/**
 * Okno `/insights` → okres, który rozumie legacy `/api/reports/invite-links`.
 *
 * `exact: false` znaczy, że tamten raport pokaże COŚ INNEGO niż obiecuje
 * etykieta wybranego okresu: nie zna granulacji rocznej i nie ma pojęcia
 * o przesunięciu (`offset`) — liczy zawsze okres BIEŻĄCY. Zwracamy tę
 * informację, zamiast po cichu podstawić kwartał: liczby jednego okna pod
 * etykietą drugiego są wiarygodne i dlatego nie do wykrycia.
 */
function legacyPeriodFor(period: InsightsPeriodParams): {
  value: Period;
  exact: boolean;
} {
  const offsetIsCurrent = (period.offset ?? 0) === 0;
  if (period.period === "year") {
    return { value: "quarter", exact: false };
  }
  if (
    period.period === "week" ||
    period.period === "month" ||
    period.period === "quarter"
  ) {
    return { value: period.period, exact: offsetIsCurrent };
  }
  return { value: "month", exact: false };
}

export function ZarzadPanel() {
  // URL jest jedynym źródłem prawdy okresu — jak w `RekrutacjaPanel`. Dawny
  // `useState` gubił wybór przy odświeżeniu i nie dawał się udostępnić linkiem.
  const router = useRouter();
  const searchParams = useSearchParams();

  const rawKind = searchParams.get("period");
  const rawOffset = Number.parseInt(searchParams.get("offset") ?? "0", 10);

  const period: InsightsPeriodParams = useMemo(
    () => ({
      period: (KINDS.includes(rawKind as InsightsPeriodKind)
        ? rawKind
        : "quarter") as InsightsPeriodKind,
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

  // Ten sam klucz co w `InsightsBoardKPI` — react-query deduplikuje, więc
  // etykieta okna nie kosztuje drugiego wywołania endpointu.
  const { data: board } = useQuery({
    queryKey: insightsQueryKeys.board(period),
    queryFn: () => insightsBoardApi.board(period),
  });

  const legacy = legacyPeriodFor(period);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Kokpit zarządu — KPI, pieniądze, trendy i Liga Mistrzów.
        </p>
        <PeriodPicker
          value={period}
          onChange={setPeriod}
          resolved={board?.period ?? null}
        />
      </div>

      <InsightsBoardKPI period={period} />

      <div className="grid grid-cols-1 gap-6">
        <ChampionsSection />

        <div className="space-y-2">
          {/* Sekcja linków siedzi na legacy `/api/reports/invite-links`, który
              nie przyjmuje ani granulacji rocznej, ani przesunięcia okna.
              Mówimy to wprost przy niej, zamiast pokazywać cudze liczby pod
              wybraną etykietą. */}
          {!legacy.exact && (
            <Degraded
              status="partial"
              reason={`Raport linków aplikacyjnych nie obsługuje wybranego okna — pokazuje BIEŻĄCY okres „${legacy.value}”, niezależnie od granulacji i przesunięcia wybranego wyżej.`}
            />
          )}
          <InviteLinksSection period={legacy.value} />
        </div>
      </div>
    </div>
  );
}
