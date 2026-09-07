/**
 * Stan sekcji Profilu Championa — krok 02 „Zlecenie i Champion" (program
 * „flow rekrutacyjny w języku C2", PR 5/7).
 *
 * Trzy stany na sekcję: pusta / wypełniona / z AI. „Z AI" pojawia się
 * WYŁĄCZNIE gdy profil niesie realny znacznik pochodzenia z parsera
 * dokumentu (`ChampionProfile._source`/`_parser` — patrz `lib/api.ts` i
 * `backend/app/schemas/champion.py::ChampionProfile.provenance`). Ten
 * znacznik jest CAŁOPROFILOWY, nie per-sekcyjny — backend nie zapisuje,
 * które sekcje ktoś nadpisał ręcznie po imporcie — więc gdy jest obecny,
 * każda WYPEŁNIONA sekcja dostaje chip „z AI"; bez niego (profil pisany
 * ręcznie albo starszy, sprzed ingestu) sekcja ma tylko dwa stany, zgodnie
 * z zasadą „nie zgaduj".
 */

import type { ChampionProfile } from "@/lib/api";

export type ChampionSectionState = "empty" | "filled" | "ai";

export const CHAMPION_SECTION_IDS = [
  "basics",
  "search",
  "stack",
  "project",
  "screening_questions",
  "client",
] as const;

export type ChampionSectionId = (typeof CHAMPION_SECTION_IDS)[number];

export interface ChampionSectionMeta {
  id: ChampionSectionId;
  /** Kotwica scrolla — dzielona przez edytor (`id` na `<section>`) i lewą nawigację. */
  anchor: string;
  label: string;
}

export const CHAMPION_SECTIONS: readonly ChampionSectionMeta[] = [
  { id: "basics", anchor: "champion-section-basics", label: "1. Podstawowe informacje" },
  { id: "search", anchor: "champion-section-search", label: "2. Co wpisać (search)" },
  { id: "stack", anchor: "champion-section-stack", label: "3. Stack technologiczny" },
  { id: "project", anchor: "champion-section-project", label: "4. O projekcie" },
  {
    id: "screening_questions",
    anchor: "champion-section-screening",
    label: "5. Pytania screeningowe",
  },
  { id: "client", anchor: "champion-section-client", label: "6. O kliencie" },
];

function hasText(value: string | null | undefined): boolean {
  return Boolean(value && value.trim().length > 0);
}

function hasItems(value: readonly unknown[] | null | undefined): boolean {
  return Array.isArray(value) && value.length > 0;
}

/**
 * Czy profil niesie realny znacznik pochodzenia z parsera dokumentu.
 * Jedyny dopuszczalny sygnał „to wypełniło AI" — patrz nagłówek modułu.
 */
export function hasChampionAiProvenance(
  profile: Pick<ChampionProfile, "_source" | "_parser"> | null | undefined,
): boolean {
  return Boolean(profile?._source || profile?._parser);
}

function isSectionFilled(id: ChampionSectionId, profile: ChampionProfile): boolean {
  switch (id) {
    case "basics": {
      const b = profile.basics;
      return (
        hasText(b.role_name) ||
        b.seniority_min_years != null ||
        b.rate_value != null ||
        hasText(b.work_mode) ||
        b.onsite_days_per_week != null ||
        hasText(b.candidate_location_pref) ||
        hasText(b.language) ||
        hasText(b.start_date) ||
        hasText(b.deadline) ||
        hasText(b.contract_length)
      );
    }
    case "search": {
      const s = profile.search;
      return (
        hasText(s.keywords) ||
        hasText(s.target_companies) ||
        hasItems(s.disqualifiers) ||
        hasText(s.notes)
      );
    }
    case "stack": {
      const st = profile.stack;
      return hasItems(st.must) || hasItems(st.nice) || hasText(st.notes);
    }
    case "project": {
      const p = profile.project;
      return hasText(p.about) || hasText(p.responsibilities);
    }
    case "screening_questions":
      return hasItems(profile.screening_questions);
    case "client": {
      const c = profile.client;
      return (
        hasText(c.selling_points) ||
        hasText(c.consultant_insight) ||
        hasText(c.historical_questions) ||
        hasItems(c.sectors)
      );
    }
    default:
      return false;
  }
}

/** Stan jednej sekcji — patrz nagłówek modułu dla zasady „z AI". */
export function championSectionState(
  id: ChampionSectionId,
  profile: ChampionProfile,
): ChampionSectionState {
  if (!isSectionFilled(id, profile)) return "empty";
  return hasChampionAiProvenance(profile) ? "ai" : "filled";
}

export const CHAMPION_SECTION_STATE_LABEL: Record<ChampionSectionState, string> = {
  empty: "Pusta",
  filled: "Wypełniona",
  ai: "Z AI",
};
