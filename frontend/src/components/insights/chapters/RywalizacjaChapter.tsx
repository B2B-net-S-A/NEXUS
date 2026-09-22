"use client";

import { InsightsCampaignBanner } from "@/components/insights/sections/InsightsCampaignBanner";
import { InsightsCampaignAdmin } from "@/components/insights/sections/InsightsCampaignAdmin";
import { ChampionsSection } from "@/components/insights/sections/ChampionsSection";
import { InsightsRaces } from "@/components/insights/sections/InsightsRaces";
import { SeniorityBoard } from "@/components/insights/sections/SeniorityBoard";
import { InsightsHallOfFame } from "@/components/insights/sections/InsightsHallOfFame";
import {
  InsightsSection,
  InsightsSectionNav,
} from "@/components/insights/InsightsSectionNav";
import { DeferUntilVisible } from "@/components/v2/DeferUntilVisible";

// Spis treści i kontrakt kotwic: każdy `id` ma odpowiadający `InsightsSection`
// niżej (pilnuje InsightsSectionNavContract.test.ts).
const SECTIONS = [
  { id: "liga", label: "Liga Mistrzów" },
  { id: "wyscigi", label: "Wyścigi miesiąca" },
  { id: "sciezka-rozwoju", label: "Ścieżka rozwoju" },
  { id: "hall-of-fame", label: "Hall of Fame" },
];

/**
 * Rozdział Rywalizacja (wariant 1 z makiet + ścieżka jako tablica z wariantu 3).
 *
 * Świadomie BEZ `PeriodPicker`a: konkursy rozstrzygają się w kwartale
 * i miesiącu według regulaminu, a Hall of Fame i ścieżka rozwoju patrzą na
 * całą historię. Pasek okresu obiecywałby wynik, którego regulamin nie zna.
 */
export function RywalizacjaChapter() {
  return (
    <div className="space-y-6">
      {/* Baner NAD wszystkim — mówi, o co zespół gra w tym okresie. Bez
          aktywnej kampanii nie renderuje nic (to normalny stan świata). */}
      <InsightsCampaignBanner />
      <InsightsCampaignAdmin />

      <InsightsSectionNav items={SECTIONS} ariaLabel="Sekcje Rywalizacji" />

      <InsightsSection id="liga">
        <ChampionsSection />
      </InsightsSection>

      <InsightsSection id="wyscigi">
        <DeferUntilVisible minHeight={240}>
          <InsightsRaces />
        </DeferUntilVisible>
      </InsightsSection>

      <InsightsSection id="sciezka-rozwoju">
        <DeferUntilVisible minHeight={240}>
          <SeniorityBoard />
        </DeferUntilVisible>
      </InsightsSection>

      <InsightsSection id="hall-of-fame">
        <DeferUntilVisible minHeight={240}>
          <InsightsHallOfFame />
        </DeferUntilVisible>
      </InsightsSection>
    </div>
  );
}
