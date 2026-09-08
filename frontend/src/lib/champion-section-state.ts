/**
 * Stan sekcji Profilu Championa — krok 02 „Zlecenie i Champion" (program
 * „flow rekrutacyjny w języku C2", PR 5/7).
 *
 * Dwa stany na sekcję: pusta / wypełniona. Pochodzenie „z AI" NIE jest
 * stanem sekcji: jedyny realny znacznik (`ChampionProfile._source`/`_parser`
 * — patrz `lib/api.ts` i `backend/app/schemas/champion.py::ChampionProfile.
 * provenance`) jest CAŁOPROFILOWY — backend nie zapisuje, które sekcje ktoś
 * nadpisał ręcznie po imporcie, a znacznik przeżywa każdy zapis. Chip „z AI"
 * przy sekcji byłby więc zgadywaniem per sekcja (i to na zawsze); zamiast
 * tego edytor pokazuje JEDEN znacznik na nagłówku profilu
 * (`hasChampionAiProvenance`). Zasada: nie zgaduj.
 */

import type { ChampionProfile } from "@/lib/api";

export type ChampionSectionState = "empty" | "filled";

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

/**
 * Kolejność WYŚWIETLANIA kroku 02, nie kolejność szablonu: 1 · 3 · (2·4·5) · 6.
 *
 * Numery w etykietach zostają szablonowe („3 · Stack technologiczny" stoi jako
 * drugi) — to one wiążą ekran z wzorem Word, po którym Delivery Leadowie się
 * poruszają, a przenumerowanie zerwałoby tę więź. Kolejność jest robocza:
 * stack idzie zaraz po podstawach, bo to on zasila `must_skills`/`nice_skills`,
 * czyli ranking C2 i filtry — a proza (2·4·5) jest tym, co bez niego i tak nie
 * ma czego rankować.
 *
 * Ta tablica JEST kolejnością renderowania — `ChampionSectionNav` mapuje po niej
 * wprost, a `ChampionProfileEditor` bierze z niej etykiety i kotwice. Jedno
 * źródło: rozjazd nawigacji z formularzem oznaczałby link prowadzący w złe
 * miejsce.
 */
export const CHAMPION_SECTIONS: readonly ChampionSectionMeta[] = [
  { id: "basics", anchor: "champion-section-basics", label: "1 · Podstawowe informacje" },
  { id: "stack", anchor: "champion-section-stack", label: "3 · Stack technologiczny" },
  { id: "search", anchor: "champion-section-search", label: "2 · Co wpisać (search)" },
  { id: "project", anchor: "champion-section-project", label: "4 · O projekcie" },
  {
    id: "screening_questions",
    anchor: "champion-section-screening",
    label: "5 · Pytania screeningowe",
  },
  { id: "client", anchor: "champion-section-client", label: "6 · O kliencie" },
];

/**
 * Sekcje 2 · 4 · 5 renderują się na kroku 02 jako JEDEN blok („proza": frazy do
 * searchu, opis projektu, pytania screeningowe). Grupa jest tu, a nie w
 * komponencie, żeby chip „N z 3 sekcji puste" i kolejność renderowania liczyły
 * się z tej samej listy.
 */
export const CHAMPION_PROSE_SECTION_IDS: readonly ChampionSectionId[] = [
  "search",
  "project",
  "screening_questions",
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

/** Stan jednej sekcji — pochodzenie profilu jest osobnym, całoprofilowym sygnałem. */
export function championSectionState(
  id: ChampionSectionId,
  profile: ChampionProfile,
): ChampionSectionState {
  return isSectionFilled(id, profile) ? "filled" : "empty";
}

export const CHAMPION_SECTION_STATE_LABEL: Record<ChampionSectionState, string> = {
  empty: "puste",
  filled: "wypełnione",
};

/**
 * Ile z podanych sekcji jest pustych — podstawa chipu grupy „proza" (2·4·5).
 *
 * Liczy z TEJ SAMEJ funkcji co chip pojedynczej sekcji, więc nagłówek grupy nie
 * może twierdzić czegoś innego niż sekcja pod nim.
 */
export function championSectionsEmptyCount(
  ids: readonly ChampionSectionId[],
  profile: ChampionProfile,
): number {
  return ids.filter((id) => championSectionState(id, profile) === "empty").length;
}

/** Etykieta znacznika pochodzenia na nagłówku profilu (jedno miejsce, nie per sekcja). */
export const CHAMPION_AI_PROVENANCE_LABEL = "Z importu (AI)";
