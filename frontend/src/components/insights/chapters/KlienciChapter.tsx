"use client";

import { useQuery } from "@tanstack/react-query";
import { PeriodPicker } from "@/components/insights/PeriodPicker";
import {
  InsightsSection,
  InsightsSectionNav,
} from "@/components/insights/InsightsSectionNav";
import {
  DlPortfolioTiles,
  InsightsDlPortfolio,
} from "@/components/insights/sections/InsightsDlPortfolio";
import { useInsightsPeriod } from "@/components/insights/useInsightsPeriod";
import { DeferUntilVisible } from "@/components/v2/DeferUntilVisible";
import { buildDlPortfolioCsvExport } from "@/lib/insights-csv";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsPeriodParams,
} from "@/lib/insights-api";

/**
 * ROK, nie miesiąc. Hit ratio stoi na rekrutacjach ZAMKNIĘTYCH w oknie, a tych
 * w pojedynczym miesiącu jest kilkanaście na cały zespół — wskaźnik z takiej
 * próbki skacze o dziesiątki punktów i wygląda jak awaria, a nie jak wynik.
 */
const DEFAULT_PERIOD: InsightsPeriodParams = { period: "year", offset: 0 };

// Spis treści i kontrakt kotwic (InsightsSectionNavContract.test.ts).
const SECTIONS = [
  { id: "podsumowanie-klientow", label: "Podsumowanie" },
  { id: "portfele", label: "Portfele DL" },
];

/**
 * Rozdział Klienci — portfele Delivery Leadów (wariant 2 z makiet).
 *
 * Zastępuje dawną zakładkę Delivery Lead (ranking DL, placementy per klient,
 * hit ratio klientów, hiring managerowie): jedna tabela, DL jako nagłówek
 * grupy, pod nim jego klienci.
 */
export function KlienciChapter() {
  const { period, setPeriod } = useInsightsPeriod(DEFAULT_PERIOD);
  const { data } = useQuery({
    queryKey: insightsQueryKeys.dlPortfolio(period),
    queryFn: () => insightsBoardApi.dlPortfolio(period),
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <InsightsSectionNav items={SECTIONS} ariaLabel="Sekcje Klientów" />
        <PeriodPicker
          value={period}
          onChange={setPeriod}
          defaultValue={DEFAULT_PERIOD}
          resolved={data?.period ?? null}
          csv={buildDlPortfolioCsvExport(data)}
        />
      </div>

      <InsightsSection id="podsumowanie-klientow">
        <DlPortfolioTiles period={period} />
      </InsightsSection>

      <InsightsSection id="portfele">
        <DeferUntilVisible minHeight={320}>
          <InsightsDlPortfolio period={period} />
        </DeferUntilVisible>
      </InsightsSection>
    </div>
  );
}
