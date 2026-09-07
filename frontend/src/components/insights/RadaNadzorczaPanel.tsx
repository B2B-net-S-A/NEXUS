"use client";

import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { PeriodPicker } from "@/components/insights/PeriodPicker";
import {
  InsightsSection,
  InsightsSectionNav,
} from "@/components/insights/InsightsSectionNav";
import {
  readPeriodFromParams,
  writePeriodToParams,
} from "@/lib/insights-period-url";
import { buildRadaCsvExport } from "@/lib/insights-csv";
import { InsightsBoardKPI } from "@/components/insights/sections/InsightsBoardKPI";
import { InsightsBoardYoY } from "@/components/insights/sections/InsightsBoardYoY";
import { InsightsClientsRanking } from "@/components/insights/sections/InsightsClientsRanking";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsPeriodParams,
} from "@/lib/insights-api";

// Domyślne okno zakładki — JEDNA stała dla odczytu z URL-a i dla „Resetu".
// Rada patrzy KWARTAŁAMI; wspólna stała dla trzech zakładek cofałaby ją
// w miejsce, od którego nigdy nie zaczyna.
const DEFAULT_PERIOD: InsightsPeriodParams = { period: "quarter", offset: 0 };

const SECTIONS = [
  { id: "kpi", label: "KPI i finanse" },
  { id: "rok-do-roku", label: "Rok do roku" },
  { id: "klienci", label: "Klienci (MRR)" },
];

export function RadaNadzorczaPanel() {
  // URL jest jedynym źródłem prawdy okresu — jak w `RekrutacjaPanel`. Dawny
  // `useState` gubił wybór przy odświeżeniu i nie dawał się udostępnić linkiem.
  const router = useRouter();
  const searchParams = useSearchParams();

  // Odczyt i zapis okresu żyją w JEDNYM module dla trzech zakładek —
  // trzy kopie tej logiki zgubiły wcześniej daty granulacji „Wszystko".
  const period: InsightsPeriodParams = useMemo(
    () => readPeriodFromParams(searchParams, DEFAULT_PERIOD),
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

  // Ranking klientów do eksportu — klucz identyczny z sekcją niżej, więc to
  // nie jest drugie wywołanie endpointu, tylko odczyt tego samego cache'u.
  const { data: ranking } = useQuery({
    queryKey: insightsQueryKeys.clientsRanking(period),
    queryFn: () => insightsBoardApi.clientsRanking(period),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Kokpit Rady Nadzorczej — KPI, pieniądze i trendy firmy oraz ranking
          klientów z MRR.
        </p>
        <PeriodPicker
          value={period}
          onChange={setPeriod}
          defaultValue={DEFAULT_PERIOD}
          resolved={board?.period ?? null}
          csv={buildRadaCsvExport(board, ranking)}
        />
      </div>

      <InsightsSectionNav items={SECTIONS} ariaLabel="Sekcje Rady Nadzorczej" />

      <InsightsSection id="kpi">
        <InsightsBoardKPI period={period} />
      </InsightsSection>

      {/* Tabele rok-do-roku — sedno układu DynaReportera dla Rady: dwanaście
          miesięcy × trzy lata, z deltą i kolumną „Ocena". Sekcja NIE przyjmuje
          okna z paska: z definicji patrzy na pełne lata kalendarzowe, a
          wpuszczenie tu `period` dałoby siatkę „ostatnie 12 miesięcy" podpisaną
          nazwami miesięcy, czyli dwie różne rzeczy pod jedną etykietą. */}
      <InsightsSection id="rok-do-roku">
        <InsightsBoardYoY />
      </InsightsSection>

      {/* Ranking klientów i MRR PRZENIESIONE tu z dawnej zakładki „Klienci
          & Delivery" (układ DynaReportera): to pytanie o pieniądze firmy —
          przychód, marżę i koncentrację portfela — a nie o obsadę, którą
          prowadzi Delivery Lead. Sekcja przyjmuje okno Rady (kwartał), więc
          wycena kafli i tabeli jest tą samą wyceną co w KPI powyżej. */}
      <InsightsSection id="klienci">
        <InsightsClientsRanking period={period} />
      </InsightsSection>
    </div>
  );
}
