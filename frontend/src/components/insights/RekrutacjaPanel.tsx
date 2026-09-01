"use client";

import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { InsightsCampaignBanner } from "@/components/insights/sections/InsightsCampaignBanner";
import { InsightsCampaignAdmin } from "@/components/insights/sections/InsightsCampaignAdmin";
import { InsightsKpiTiles } from "@/components/insights/sections/InsightsKpiTiles";
import { InsightsTeamPerformance } from "@/components/insights/sections/InsightsTeamPerformance";
import { InsightsRaces } from "@/components/insights/sections/InsightsRaces";
import { InsightsHallOfFame } from "@/components/insights/sections/InsightsHallOfFame";
import { InsightsYearlyStats } from "@/components/insights/sections/InsightsYearlyStats";
import { InsightsPlacementAnalysis } from "@/components/insights/sections/InsightsPlacementAnalysis";
import { InsightsPowerCalling } from "@/components/insights/sections/InsightsPowerCalling";
import { InsightsLinkedIn } from "@/components/insights/sections/InsightsLinkedIn";
import { InsightsTeamActivity } from "@/components/insights/sections/InsightsTeamActivity";
import { RecruitmentFunnel } from "@/components/insights/sections/RecruitmentFunnel";
import { RecruitmentConversions } from "@/components/insights/sections/RecruitmentConversions";
import { InsightsTimeToHire } from "@/components/insights/sections/InsightsTimeToHire";
import { InsightsSeniority } from "@/components/insights/sections/InsightsSeniority";
import { SourcesFunnelSection } from "@/components/insights/sections/SourcesFunnelSection";
import { PeriodPicker } from "@/components/insights/PeriodPicker";
import {
  DEFAULT_INSIGHTS_OFFSET,
  insightsApi,
  type InsightsPeriodKind,
  type InsightsPeriodParams,
} from "@/lib/insights-api";

const KINDS: InsightsPeriodKind[] = ["week", "month", "quarter", "year"];

export function RekrutacjaPanel() {
  // URL jest jedynym źródłem prawdy okresu — back/forward odtwarza wybór,
  // a link da się udostępnić. Stan w `useState` gubił się przy odświeżeniu.
  const router = useRouter();
  const searchParams = useSearchParams();

  const rawKind = searchParams.get("period");
  const rawOffsetParam = searchParams.get("offset");
  const rawOffset =
    rawOffsetParam === null
      ? DEFAULT_INSIGHTS_OFFSET
      : Number.parseInt(rawOffsetParam, 10);

  const period: InsightsPeriodParams = useMemo(
    () => ({
      period: (KINDS.includes(rawKind as InsightsPeriodKind)
        ? rawKind
        : "month") as InsightsPeriodKind,
      offset: Number.isFinite(rawOffset) ? rawOffset : DEFAULT_INSIGHTS_OFFSET,
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
  const { data: funnel } = useQuery({
    queryKey: ["insights", "recruitment", "funnel", period],
    queryFn: () => insightsApi.recruitmentFunnel(period),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Lejek, konwersje, time-to-hire, wyniki per osoba, wyścigi miesiąca
          i źródła kandydatów.
        </p>
        <PeriodPicker
          value={period}
          onChange={setPeriod}
          resolved={funnel?.period ?? null}
        />
      </div>

      {/* Baner kampanii NAD wszystkim — w oryginale to pierwsza rzecz na
          stronie, bo mówi, o co zespół gra w tym okresie. Bez aktywnej
          kampanii komponent nie renderuje nic (nie pusty stan: brak kampanii
          to normalny stan świata, nie brak danych). */}
      <InsightsCampaignBanner />
      {/* Panel zakładania kampanii — bez niego baner powyżej nigdy nie ma co
          pokazać, bo kampanii nie da się nigdzie utworzyć. Renderuje się
          wyłącznie dla admina i sam z siebie znika dla reszty zespołu. */}
      <InsightsCampaignAdmin />

      {/* Cztery liczby, od których zaczyna się rozmowa o rekrutacji —
          nad lejkiem, jak w DynaReporterze. Ta sama koperta co lejek
          i konwersje (jeden klucz react-query), więc kafel nie ma jak
          rozjechać się z paskiem pod nim. */}
      <InsightsKpiTiles period={period} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <RecruitmentFunnel period={period} />
        <RecruitmentConversions period={period} />
      </div>

      <InsightsTimeToHire period={period} />

      {/* D7: bramka rolowa na imiennym rankingu zdjęta — /insights widzi każda
          zalogowana rola. Nie przywracaj jej tutaj bez zmiany decyzji w
          docs/insights-dynareporter-migration-plan.md §0 D7; ukryta sekcja
          przy otwartym API to split-brain, nie zabezpieczenie.

          Sama bramka we froncie nie wystarczała: sekcja wołała
          `/api/activities/leaderboard`, który stoi na capability
          `VIEW_RECRUITMENT_RANKING` — rola `user` ma tam pustą frozenset, więc
          dostawała 403 i widziała go jako „brak danych o zespole". Teraz jedzie
          na `/api/insights/recruitment/team-activity` (`CurrentUser`), które
          w dodatku przyjmuje TO SAMO okno co reszta zakładki — legacy liczył
          okno kroczące i ignorował `PeriodPicker`. */}
      <InsightsTeamActivity period={period} />

      {/* Wykresy roczne. Świadomie POZA `PeriodPicker`em: to widok
          dwunastu miesięcy roku, a przycięcie go oknem miesiąca zostawiłoby
          jeden punkt i wykres bez sensu. Rok domyślny bierze SERWER. */}
      <InsightsYearlyStats />

      {/* Analiza placementów — kto i u kogo. Ta sekcja PRZYJMUJE okno z paska:
          pytanie „kto dowiózł w tym miesiącu" ma sens tylko z okresem. */}
      <InsightsPlacementAnalysis period={period} />

      {/* „Performance per osoba" — serce zakładki w oryginale. Plakietki
          ostrzeżeń wstrzykiwane z osobnego zapytania, żeby ich awaria nie
          przewracała tabeli wyników (patrz InsightsTeamPerformance). */}
      <InsightsTeamPerformance period={period} />

      {/* Wyścigi miesiąca i Hall of Fame. Świadomie NIE przyjmują `period`
          z paska u góry: konkurs jest rozstrzygany w MIESIĄCU i KWARTALE,
          a podpięcie ich pod tydzień albo dowolne okno obiecywałoby wynik,
          którego regulamin nie zna. */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <InsightsRaces />
        <InsightsHallOfFame />
      </div>

      {/* Power Calling ma własny wybór TYGODNIA (endpoint zna wyłącznie
          `offset_weeks`), a LinkedIn własny przełącznik okresu — obie sekcje
          są tu opisane w swoich plikach i celowo nie udają, że słuchają
          `PeriodPicker`a. */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <InsightsPowerCalling />
        <InsightsLinkedIn />
      </div>

      {/* Ścieżka rozwoju (D6) — poziom z liczby placementów, liczony przy
          odczycie. Sekcja świadomie NIE przyjmuje `period`: poziom jest
          funkcją CAŁEJ historii, a przycięcie jej oknem `PeriodPicker`a
          zamieniłoby zapadkę awansu w licznik, który spada. */}
      <InsightsSeniority />

      <SourcesFunnelSection />
    </div>
  );
}
