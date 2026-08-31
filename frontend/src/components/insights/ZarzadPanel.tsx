"use client";

import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { PeriodPicker } from "@/components/insights/PeriodPicker";
import { ChampionsSection } from "@/components/insights/sections/ChampionsSection";
import { InsightsBoardKPI } from "@/components/insights/sections/InsightsBoardKPI";
import { InsightsInviteLinks } from "@/components/insights/sections/InsightsInviteLinks";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsPeriodKind,
  type InsightsPeriodParams,
} from "@/lib/insights-api";

const KINDS: InsightsPeriodKind[] = ["week", "month", "quarter", "year"];

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

        {/* Sekcja linków jedzie na `/api/insights/recruitment/invite-links`
            (`CurrentUser`), więc przyjmuje TO SAMO okno co reszta kokpitu.
            Zniknął razem z tym `Degraded` ostrzegający, że legacy
            `/api/reports/invite-links` pokazuje BIEŻĄCY okres niezależnie od
            wybranej granulacji i przesunięcia — i zniknęło 403, które ten
            raport zwracał recruiterowi, sourcerowi i tacowi na zakładce
            otwartej pod D7 dla każdej zalogowanej roli. */}
        <InsightsInviteLinks period={period} />
      </div>
    </div>
  );
}
