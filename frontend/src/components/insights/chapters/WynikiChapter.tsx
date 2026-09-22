"use client";

import { useQuery } from "@tanstack/react-query";
import { InsightsKpiTiles } from "@/components/insights/sections/InsightsKpiTiles";
import { RecruitmentFunnel } from "@/components/insights/sections/RecruitmentFunnel";
import { RecruitmentConversions } from "@/components/insights/sections/RecruitmentConversions";
import { InsightsTimeToHire } from "@/components/insights/sections/InsightsTimeToHire";
import { InsightsYearlyStats } from "@/components/insights/sections/InsightsYearlyStats";
import { InsightsTeamPerformance } from "@/components/insights/sections/InsightsTeamPerformance";
import { InsightsTeamActivity } from "@/components/insights/sections/InsightsTeamActivity";
import { CompetenceMatrix } from "@/components/insights/sections/CompetenceMatrix";
import { InsightsPlacementAnalysis } from "@/components/insights/sections/InsightsPlacementAnalysis";
import { InsightsIntegrations } from "@/components/insights/sections/InsightsIntegrations";
import { SourcesFunnelSection } from "@/components/insights/sections/SourcesFunnelSection";
import { InsightsInviteLinks } from "@/components/insights/sections/InsightsInviteLinks";
import { RecruitmentActivityDashboard } from "@/components/v2/dashboard/RecruitmentActivityDashboard";
import { AllocationWorkloadBoard } from "@/components/v2/priority-work/AllocationWorkloadBoard";
import { PeriodPicker } from "@/components/insights/PeriodPicker";
import { InsightsDisclosure } from "@/components/insights/InsightsDisclosure";
import { InsightsPartHeading } from "@/components/insights/InsightsPartHeading";
import {
  InsightsSection,
  InsightsSectionNav,
} from "@/components/insights/InsightsSectionNav";
import { useInsightsPeriod } from "@/components/insights/useInsightsPeriod";
import { DeferUntilVisible } from "@/components/v2/DeferUntilVisible";
import { buildFunnelCsvExport } from "@/lib/insights-csv";
import {
  DEFAULT_INSIGHTS_OFFSET,
  insightsApi,
  type InsightsPeriodParams,
} from "@/lib/insights-api";
import { hasSectionAccess } from "@/lib/section-access";
import { hasRole, useAuthStore } from "@/store/auth";

const DEFAULT_PERIOD: InsightsPeriodParams = {
  period: "month",
  offset: DEFAULT_INSIGHTS_OFFSET,
};

// Spis treści i kontrakt kotwic (InsightsSectionNavContract.test.ts).
const SECTIONS = [
  { id: "wynik", label: "Wynik" },
  { id: "aktywnosc", label: "Dziś i w miesiącu" },
  { id: "zespol", label: "Zespół" },
  { id: "praca", label: "Praca w toku" },
  { id: "doplyw", label: "Dopływ kandydatów" },
];

/**
 * Rozdział Wyniki — dane z trzech paneli makiety (lejek, „ja na tle zespołu",
 * praca w toku) + Integracje z usuniętej zakładki Aktywność.
 *
 * Pasek okresu steruje WYNIKIEM, ZESPOŁEM i PLACEMENTAMI. Trzy wyjątki mają
 * własne okna i tak zostaje: aktywność dnia/miesiąca (to jej sens), macierz
 * kompetencji (stan na dziś) oraz integracje i źródła (7/30/90 dni).
 */
export function WynikiChapter() {
  const user = useAuthStore((s) => s.user);
  const { period, setPeriod } = useInsightsPeriod(DEFAULT_PERIOD);

  // Etykieta okna z SERWERA — ten sam klucz co lejek i kafle, więc to nie
  // jest drugie wywołanie endpointu.
  const { data: funnel } = useQuery({
    queryKey: ["insights", "recruitment", "funnel", period],
    queryFn: () => insightsApi.recruitmentFunnel(period),
  });

  // Obie powierzchnie z pulpitu stoją za sekcją Rekrutacje (pipeline), a
  // obłożenie dodatkowo za HoR/adminem (`HeadOfRecruitmentOnly`). Bez tych
  // warunków rola spoza nich zobaczyłaby kartę błędu 403 zamiast danych.
  const canReadPipeline = hasSectionAccess(user, "pipeline");
  const canSeeWorkload =
    canReadPipeline && hasRole(user, "admin", "head_of_recruitment");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <InsightsSectionNav items={SECTIONS} ariaLabel="Sekcje Wyników" />
        <PeriodPicker
          value={period}
          onChange={setPeriod}
          defaultValue={DEFAULT_PERIOD}
          resolved={funnel?.period ?? null}
          csv={buildFunnelCsvExport(funnel)}
        />
      </div>

      <InsightsSection id="wynik" className="space-y-4">
        <InsightsPartHeading
          title="Wynik"
          hint="pierwsze wejście na etap w wybranym okresie"
        />
        <InsightsKpiTiles period={period} />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <RecruitmentFunnel period={period} />
          <RecruitmentConversions period={period} />
        </div>
        <InsightsTimeToHire period={period} />
        <InsightsDisclosure title="Trendy roczne" hint="12 miesięcy · rozwiń">
          <InsightsYearlyStats />
        </InsightsDisclosure>
      </InsightsSection>

      <InsightsSection id="aktywnosc" className="space-y-4">
        <DeferUntilVisible minHeight={240}>
          <InsightsPartHeading
            title="Dziś i w miesiącu"
            hint="dzienny cel, Twoje liczby i porównanie ze średnią zespołu"
          />
          {canReadPipeline ? (
            <RecruitmentActivityDashboard showNextSteps={false} embedded />
          ) : (
            <p className="rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground">
              Aktywność dnia i miesiąca jest dostępna dla osób z dostępem do
              sekcji Rekrutacje.
            </p>
          )}
        </DeferUntilVisible>
      </InsightsSection>

      <InsightsSection id="zespol" className="space-y-4">
        <DeferUntilVisible minHeight={240}>
          <InsightsPartHeading
            title="Zespół"
            hint="kto ile dowiózł i kto ma ile pracy"
          />
          <InsightsTeamPerformance period={period} />
          <InsightsDisclosure
            title="Aktywność zespołu"
            hint="kandydaci, screeningi, rozmowy, telefony · rozwiń"
          >
            <InsightsTeamActivity period={period} />
          </InsightsDisclosure>
          {canSeeWorkload ? (
            // Zwinięte: ~40 kart osób, w większości zerowych, przykrywało
            // resztę rozdziału. To narzędzie HoR-a, nie statystyka dla zespołu.
            <InsightsDisclosure
              title="Obłożenie i zastępstwa"
              hint="tylko HoR i admin · rozwiń"
            >
              <AllocationWorkloadBoard />
            </InsightsDisclosure>
          ) : null}
        </DeferUntilVisible>
      </InsightsSection>

      <InsightsSection id="praca" className="space-y-4">
        <DeferUntilVisible minHeight={240}>
          <InsightsPartHeading
            title="Praca w toku"
            hint="gdzie są rekrutacje i komu / u kogo były placementy"
          />
          <CompetenceMatrix />
          <InsightsPlacementAnalysis period={period} />
        </DeferUntilVisible>
      </InsightsSection>

      <InsightsSection id="doplyw" className="space-y-4">
        <DeferUntilVisible minHeight={240}>
          <InsightsPartHeading
            title="Dopływ kandydatów"
            hint="integracje z portalami, źródła i linki aplikacyjne"
          />
          <InsightsIntegrations />
          <SourcesFunnelSection />
          <InsightsInviteLinks period={period} />
        </DeferUntilVisible>
      </InsightsSection>
    </div>
  );
}
