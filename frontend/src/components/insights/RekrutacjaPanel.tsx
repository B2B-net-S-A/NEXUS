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
import { InsightsInviteLinks } from "@/components/insights/sections/InsightsInviteLinks";
import { ChampionsSection } from "@/components/insights/sections/ChampionsSection";
import { RecruitmentFunnel } from "@/components/insights/sections/RecruitmentFunnel";
import { RecruitmentConversions } from "@/components/insights/sections/RecruitmentConversions";
import { InsightsTimeToHire } from "@/components/insights/sections/InsightsTimeToHire";
import { InsightsSeniority } from "@/components/insights/sections/InsightsSeniority";
import { SourcesFunnelSection } from "@/components/insights/sections/SourcesFunnelSection";
import { PeriodPicker } from "@/components/insights/PeriodPicker";
import {
  InsightsSection,
  InsightsSectionNav,
} from "@/components/insights/InsightsSectionNav";
import {
  readPeriodFromParams,
  writePeriodToParams,
} from "@/lib/insights-period-url";
import { buildFunnelCsvExport } from "@/lib/insights-csv";
import {
  DEFAULT_INSIGHTS_OFFSET,
  insightsApi,
  type InsightsPeriodParams,
} from "@/lib/insights-api";

// Domyślne okno zakładki — JEDNA stała dla odczytu z URL-a i dla „Resetu".
// Rozdzielone, „Reset" wracał do czegoś, od czego zakładka nigdy nie zaczyna.
const DEFAULT_PERIOD: InsightsPeriodParams = {
  period: "month",
  offset: DEFAULT_INSIGHTS_OFFSET,
};

// Kolejność sekcji jest lustrem DynaReportera — zespół zna tamten porządek
// i tamte nazwy. Ta tablica jest jednocześnie spisem treści i kontraktem
// kotwic: każdy `id` musi mieć odpowiadający `InsightsSection` niżej.
const SECTIONS = [
  { id: "podsumowanie", label: "Podsumowanie" },
  { id: "lejek", label: "Lejek" },
  { id: "zespol", label: "Zespół" },
  { id: "liga", label: "Liga i wyścigi" },
  { id: "trendy", label: "Trendy roczne" },
  { id: "placementy", label: "Placementy" },
  { id: "aktywnosc", label: "Power Calling · LinkedIn" },
  { id: "sciezka-rozwoju", label: "Ścieżka rozwoju" },
  { id: "zrodla", label: "Źródła" },
];

export function RekrutacjaPanel() {
  // URL jest jedynym źródłem prawdy okresu — back/forward odtwarza wybór,
  // a link da się udostępnić. Stan w `useState` gubił się przy odświeżeniu.
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
          Lejek, konwersje, time-to-hire, wyniki per osoba, Liga Mistrzów,
          wyścigi miesiąca i źródła kandydatów.
        </p>
        <PeriodPicker
          value={period}
          onChange={setPeriod}
          defaultValue={DEFAULT_PERIOD}
          resolved={funnel?.period ?? null}
          // Bez tego propu przycisk „Eksportuj" nie renderuje się w ogóle —
          // był zaimplementowany i przetestowany, ale jedynym miejscem
          // w repo, które go podawało, był test pickera.
          csv={buildFunnelCsvExport(funnel)}
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

      <InsightsSectionNav items={SECTIONS} ariaLabel="Sekcje Rekrutacji" />

      {/* Cztery liczby, od których zaczyna się rozmowa o rekrutacji —
          nad lejkiem, jak w DynaReporterze. Ta sama koperta co lejek
          i konwersje (jeden klucz react-query), więc kafel nie ma jak
          rozjechać się z paskiem pod nim. */}
      <InsightsSection id="podsumowanie">
        <InsightsKpiTiles period={period} />
      </InsightsSection>

      <InsightsSection id="lejek" className="space-y-6">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <RecruitmentFunnel period={period} />
          <RecruitmentConversions period={period} />
        </div>
        <InsightsTimeToHire period={period} />
      </InsightsSection>

      {/* „Performance per osoba" — serce zakładki w oryginale, więc stoi
          bezpośrednio pod lejkiem, a nie za wykresami rocznymi. Plakietki
          ostrzeżeń wstrzykiwane z osobnego zapytania, żeby ich awaria nie
          przewracała tabeli wyników (patrz InsightsTeamPerformance).

          D7: bramka rolowa na imiennym rankingu zdjęta — /insights widzi każda
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
      <InsightsSection id="zespol" className="space-y-6">
        <InsightsTeamPerformance period={period} />
        <InsightsTeamActivity period={period} />
      </InsightsSection>

      {/* Liga Mistrzów PRZENIESIONA tu z dawnej zakładki „Zarząd" (układ
          DynaReportera): gamifikacja rekrutacyjna żyje na stronie zespołu,
          obok wyścigów i Hall of Fame, a nie w kokpicie Rady. Sekcja
          świadomie NIE przyjmuje `period` z paska u góry — tak samo jak
          wyścigi: konkurs jest rozstrzygany w KWARTALE i MIESIĄCU, a
          podpięcie go pod dowolne okno obiecywałoby wynik, którego regulamin
          nie zna. */}
      <InsightsSection id="liga" className="space-y-6">
        <ChampionsSection />
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <InsightsRaces />
          <InsightsHallOfFame />
        </div>
      </InsightsSection>

      {/* Wykresy roczne. Świadomie POZA `PeriodPicker`em: to widok
          dwunastu miesięcy roku, a przycięcie go oknem miesiąca zostawiłoby
          jeden punkt i wykres bez sensu. Rok domyślny bierze SERWER. */}
      <InsightsSection id="trendy">
        <InsightsYearlyStats />
      </InsightsSection>

      {/* Analiza placementów — kto i u kogo. Ta sekcja PRZYJMUJE okno z paska:
          pytanie „kto dowiózł w tym miesiącu" ma sens tylko z okresem. */}
      <InsightsSection id="placementy">
        <InsightsPlacementAnalysis period={period} />
      </InsightsSection>

      {/* Power Calling ma własny wybór TYGODNIA (endpoint zna wyłącznie
          `offset_weeks`), a LinkedIn własny przełącznik okresu — obie sekcje
          są tu opisane w swoich plikach i celowo nie udają, że słuchają
          `PeriodPicker`a. */}
      <InsightsSection id="aktywnosc">
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <InsightsPowerCalling />
          <InsightsLinkedIn />
        </div>
      </InsightsSection>

      {/* Ścieżka rozwoju (D6) — poziom z liczby placementów, liczony przy
          odczycie. Sekcja świadomie NIE przyjmuje `period`: poziom jest
          funkcją CAŁEJ historii, a przycięcie jej oknem `PeriodPicker`a
          zamieniłoby zapadkę awansu w licznik, który spada. */}
      <InsightsSection id="sciezka-rozwoju">
        <InsightsSeniority />
      </InsightsSection>

      {/* Źródła kandydatów. Linki aplikacyjne PRZENIESIONE tu z dawnej
          zakładki „Zarząd": to pytanie „skąd przyszli kandydaci", czyli ta
          sama rozmowa co lejek źródeł obok, a nie temat kokpitu Rady. */}
      <InsightsSection id="zrodla" className="space-y-6">
        <SourcesFunnelSection />
        <InsightsInviteLinks period={period} />
      </InsightsSection>
    </div>
  );
}
