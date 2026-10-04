/**
 * „Profil Championa” w czterech zakładkach (decyzje Artura 04.10.2026,
 * makiety https://claude.ai/artifact/FwQr2uYhWcRfdDeWdbStUc).
 *
 * Podzakładki widoku i bloki, które da się edytować w szufladzie. Blok to
 * kawałek Briefu (albo zakładki „Klient i historia”), a jego edycja pokazuje
 * WYŁĄCZNIE sekcje edytora z tej listy — reszta formularza zostaje pod
 * „⋯ → Edytuj cały Profil Championa”.
 */

import {
  CHAMPION_SECTIONS,
  SEARCH_REQUIREMENTS_ANCHOR,
  type ChampionSectionId,
} from "@/lib/champion-section-state";

/** Podzakładki widoku (`?ptab=`). */
export type ChampionTab = "brief" | "tech" | "client" | "team";

export const CHAMPION_TABS: readonly { value: ChampionTab; label: string }[] = [
  { value: "brief", label: "Brief" },
  { value: "tech", label: "Technologie po ludzku" },
  { value: "client", label: "Klient i historia" },
  { value: "team", label: "Zespół i ogłoszenie" },
];

/**
 * `?ptab=` → zakładka. Stare wartości z panelu bocznego (do 04.10.2026)
 * zostają czytelne: „Gotowość” to dziś Brief z paskiem „Do dopięcia”,
 * a „Zespół” i „Ogłoszenie” to jedna zakładka.
 */
export function resolveChampionTab(raw: string | null | undefined): ChampionTab | null {
  switch (raw) {
    case "brief":
    case "tech":
    case "client":
    case "team":
      return raw;
    case "readiness":
      return "brief";
    case "announce":
      return "team";
    default:
      return null;
  }
}

/** Bloki z przyciskiem „Edytuj”. */
export type ChampionBlock =
  | "conditions"
  | "search"
  | "project"
  | "screening"
  | "client"
  | "insights";

export interface ChampionBlockMeta {
  title: string;
  /** Sekcje edytora pokazywane w szufladzie (kolejność = kolejność edytora). */
  sections: readonly ChampionSectionId[];
}

export const CHAMPION_BLOCKS: Record<ChampionBlock, ChampionBlockMeta> = {
  conditions: { title: "Warunki", sections: ["basics"] },
  search: { title: "Czego szukamy", sections: ["stack", "experience", "search"] },
  project: { title: "O projekcie", sections: ["project"] },
  screening: { title: "Pytania na rozmowę", sections: ["screening_questions"] },
  client: { title: "O kliencie", sections: ["client"] },
  insights: { title: "Wiedza z rozmów", sections: ["insights"] },
};

const SECTION_TO_BLOCK: Record<ChampionSectionId, ChampionBlock> = {
  basics: "conditions",
  stack: "search",
  experience: "search",
  search: "search",
  project: "project",
  screening_questions: "screening",
  client: "client",
  insights: "insights",
};

/**
 * Kotwica sekcji (`champion-section-*`, z braków bramki i ostrzeżeń) → blok,
 * którego szuflada tę sekcję pokazuje. Nieznana kotwica = `null` (pełny
 * formularz).
 */
export function blockForAnchor(anchor: string | null | undefined): ChampionBlock | null {
  if (!anchor) return null;
  if (anchor === SEARCH_REQUIREMENTS_ANCHOR) return "search";
  const section = CHAMPION_SECTIONS.find((s) => s.anchor === anchor);
  return section ? SECTION_TO_BLOCK[section.id] : null;
}
