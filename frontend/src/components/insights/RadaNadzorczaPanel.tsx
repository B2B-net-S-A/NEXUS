"use client";

import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { PeriodPicker } from "@/components/insights/PeriodPicker";
import {
  InsightsSection,
  InsightsSectionNav,
} from "@/components/insights/InsightsSectionNav";
import { DeferUntilVisible } from "@/components/v2/DeferUntilVisible";
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

// Rok do roku NA GÓRZE (decyzja z makiet 21.09.2026), kokpit i ranking
// klientów niżej.
const SECTIONS = [
  { id: "rok-do-roku", label: "Rok do roku" },
  { id: "kpi", label: "KPI i finanse" },
  { id: "klienci", label: "Klienci (MRR)" },
];

export function RadaNadzorczaPanel() {
  // URL jest jedynym źródłem prawdy okresu — jak w rozdziałach Body Leasing. Dawny
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
      {/* Poniżej `lg` opis nad paskiem okresu — obok siebie akapit ściskał
          się do jednego słowa w linii (audyt 23.09.2026, P1-07). */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <p className="text-sm text-muted-foreground lg:max-w-xl">
          Rok do roku, kokpit KPI i ranking klientów z MRR. Pasek okresu
          steruje kokpitem i rankingiem — rok do roku patrzy na pełne lata.
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

      {/* Tabele rok-do-roku — sedno układu DynaReportera dla Rady: dwanaście
          miesięcy × trzy lata, z deltą i kolumną „Ocena". Sekcja NIE przyjmuje
          okna z paska: z definicji patrzy na pełne lata kalendarzowe, a
          wpuszczenie tu `period` dałoby siatkę „ostatnie 12 miesięcy" podpisaną
          nazwami miesięcy, czyli dwie różne rzeczy pod jedną etykietą. */}
      <InsightsSection id="rok-do-roku">
        <InsightsBoardYoY />
      </InsightsSection>

      <InsightsSection id="kpi">
        <DeferUntilVisible minHeight={240}>
          <InsightsBoardKPI period={period} />
        </DeferUntilVisible>
      </InsightsSection>

      {/* Ranking klientów i MRR PRZENIESIONE tu z dawnej zakładki „Klienci
          & Delivery" (układ DynaReportera): to pytanie o pieniądze firmy —
          przychód, marżę i koncentrację portfela — a nie o obsadę, którą
          prowadzi Delivery Lead. Sekcja przyjmuje okno Rady (kwartał), więc
          wycena kafli i tabeli jest tą samą wyceną co w KPI powyżej. */}
      <InsightsSection id="klienci">
        <DeferUntilVisible minHeight={240}>
          <InsightsClientsRanking period={period} />
        </DeferUntilVisible>
      </InsightsSection>
    </div>
  );
}
