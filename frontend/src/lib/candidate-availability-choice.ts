/**
 * Uproszczone filtry listy kandydatów (makieta 22.09.2026,
 * https://claude.ai/artifact/FZL7d1BycnJ4vXWB6ncf1s).
 *
 * JEDNO pytanie „Czy można go teraz zaproponować?" (sekcja „Dostępność”
 * w „Zaawansowanych”) zamiast dwóch grup mówiących o tym samym innymi słowami
 * (Dostępność, Zatrudnienie). Odpowiedź łączy dwa parametry API tak, żeby
 * wynik znaczył to, co mówi etykieta: „szuka pracy" samo z siebie zostawiałoby
 * na liście konsultantów pracujących u naszego klienta.
 *
 * Czyste funkcje, bez Reacta — testowane na wartościach.
 */

import type { CandidateFilters } from "@/lib/url-filters";

const sameSet = (a: readonly string[], b: readonly string[]) =>
  a.length === b.length && a.every((v) => b.includes(v));

// ── 1. „Czy można go teraz zaproponować?" ─────────────────────────────────

export type AvailabilityChoiceId =
  | "all"
  | "open"
  | "at_client"
  | "ending_soon"
  | "not_looking"
  | "unknown";

export interface AvailabilityChoice {
  id: AvailabilityChoiceId;
  label: string;
  hint?: string;
  patch: Pick<CandidateFilters, "availability" | "employment">;
}

export const AVAILABILITY_CHOICES: readonly AvailabilityChoice[] = [
  { id: "all", label: "Bez znaczenia", patch: { availability: [], employment: [] } },
  {
    id: "open",
    label: "Tak — szuka pracy albo jest otwarty",
    hint: "nie pracuje teraz u nas",
    patch: { availability: ["actively_looking", "open_to_offers"], employment: ["available"] },
  },
  {
    id: "at_client",
    // Ta sama nazwa co znacznik przy nazwisku („Pracuje u nas”).
    label: "Pracuje u nas",
    hint: "nasz konsultant na projekcie",
    patch: { availability: [], employment: ["at_client"] },
  },
  {
    id: "ending_soon",
    label: "Kończy u nas w ciągu 60 dni",
    hint: "zamówienie bez kontynuacji",
    patch: { availability: [], employment: ["ending_soon"] },
  },
  {
    id: "not_looking",
    label: "Nie szuka",
    patch: { availability: ["not_looking"], employment: ["available"] },
  },
  {
    id: "unknown",
    label: "Nie wiemy",
    hint: "brak informacji o dostępności",
    patch: { availability: ["unknown"], employment: ["available"] },
  },
];

/**
 * Która odpowiedź pasuje do bieżących filtrów. `null` = ustawienie spoza
 * pytania (stary link, zapisane wyszukiwanie) — pokazujemy je uczciwie jako
 * „własne ustawienie", zamiast zaznaczać odpowiedź, która go nie opisuje.
 */
export function availabilityChoiceFor(
  filters: Pick<CandidateFilters, "availability" | "employment">,
): AvailabilityChoiceId | null {
  const hit = AVAILABILITY_CHOICES.find(
    (c) =>
      sameSet(c.patch.availability, filters.availability) &&
      sameSet(c.patch.employment, filters.employment),
  );
  return hit?.id ?? null;
}
