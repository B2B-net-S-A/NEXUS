import type { AvailabilityStatusValue } from "@/lib/candidate-search-api";

/**
 * Etykiety dostępności wyszukiwarki. Status `open_to_offers` w całej aplikacji
 * brzmi „Otwarty na oferty" (CLAUDE.md, „Nazewnictwo"); od 22.09.2026 lista
 * (`lib/filter-options.ts`), profil i Cortex mówią to samo — dwa tryby ekranu
 * „Kandydaci" nie mogą nazywać jednej wartości dwoma nazwami. Wspólne dla filtra (`FiltersPanel`)
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

