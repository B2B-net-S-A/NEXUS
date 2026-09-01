"use client";

import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { PeriodPicker } from "@/components/insights/PeriodPicker";
import {
  readPeriodFromParams,
  writePeriodToParams,
} from "@/lib/insights-period-url";
import { buildBoardCsvExport } from "@/lib/insights-csv";
import { ChampionsSection } from "@/components/insights/sections/ChampionsSection";
import { InsightsBoardKPI } from "@/components/insights/sections/InsightsBoardKPI";
import { InsightsInviteLinks } from "@/components/insights/sections/InsightsInviteLinks";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsPeriodParams,
} from "@/lib/insights-api";

export function ZarzadPanel() {
  // URL jest jedynym źródłem prawdy okresu — jak w `RekrutacjaPanel`. Dawny
  // `useState` gubił wybór przy odświeżeniu i nie dawał się udostępnić linkiem.
  const router = useRouter();
  const searchParams = useSearchParams();

  // Odczyt i zapis okresu żyją w JEDNYM module dla trzech zakładek —
  // trzy kopie tej logiki zgubiły wcześniej daty granulacji „Wszystko".
  // Domyślne (kwartał, bieżący) zostają takie jak były: Zarząd patrzy
  // kwartałami i ujednolicenie ich tutaj byłoby cichą zmianą jego widoku.
  const period: InsightsPeriodParams = useMemo(
    () => readPeriodFromParams(searchParams, { kind: "quarter", offset: 0 }),
    [searchParams],
  );

  const setPeriod = useCallback(
    (next: InsightsPeriodParams) => {
      const params = writePeriodToParams(searchParams, next);
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
          csv={buildBoardCsvExport(board)}
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
