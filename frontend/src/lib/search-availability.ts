import type { AvailabilityStatusValue } from "@/lib/candidate-search-api";

/**
 * Etykiety dostępności wyszukiwarki. Świadomie NIE z `lib/filter-options.ts`
 * („Otwarty na projekty") — status `open_to_offers` w całej aplikacji
 * (profil, podgląd, kafelki, dok pipeline'u) brzmi „Otwarty na oferty" i tak
 * ma zostać (CLAUDE.md, „Nazewnictwo"). Wspólne dla filtra (`FiltersPanel`)
 * i wierszy wyników (`CandidateSearchView`), żeby mówiły to samo. Osobny moduł,
 * bo testy widoku mockują cały `FiltersPanel`.
 */
export const SEARCH_AVAILABILITY_OPTIONS: {
  value: AvailabilityStatusValue;
  label: string;
}[] = [
  { value: "actively_looking", label: "Aktywnie szuka" },
  { value: "open_to_offers", label: "Otwarty na oferty" },
  { value: "not_looking", label: "Nie szuka" },
  { value: "unknown", label: "Nieznane" },
];

