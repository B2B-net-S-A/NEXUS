"use client";

import type { ReactNode } from "react";
import { Info } from "lucide-react";
import { formatPLN } from "./_shared";

/**
 * Formatowanie liczb dla powierzchni `/api/insights/*`.
 *
 * Cały ten plik istnieje dla JEDNEJ różnicy: `null` znaczy „nie dało się
 * policzyć", a `0` znaczy „policzone i wyszło zero". Backend utrzymuje ją
 * konsekwentnie (`_ratio` zwraca `None`, nigdy `0.0`), więc front nie może jej
 * zgubić w `?? 0` — na ekranie z pieniędzmi zero jest werdyktem, a myślnik
 * pytaniem.
 */

/** Kwota w PLN albo „—”. NIGDY nie podstawiaj `0` za `null`. */
export function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return formatPLN(value);
}

/** Liczba całkowita albo „—”. */
export function count(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("pl-PL");
}

/**
 * Procent albo „—”. Świadomie BEZ przycinania do 100: wynik powyżej stu
 * procent znaczy, że licznik i mianownik pochodzą z różnych populacji
 * (np. placementy z zapytań spoza okna) i ma to być widoczne, a nie schowane
 * pod sufitem osi.
 */
export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(digits)}%`;
}

/**
 * Szerokość paska w procentach szerokości toru.
 *
 * To jedyne miejsce, w którym wolno ograniczyć wartość do 100 — pasek nie ma
 * jak wyjść poza swój tor. Liczba obok paska musi zostać nieprzycięta
 * (`pct`), inaczej 120% wyglądałoby jak równe sto.
 */
export function barWidth(value: number | null | undefined): number {
  if (value === null || value === undefined || Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(value, 100));
}

/** Zmiana w punktach procentowych ze znakiem, albo „—”. */
export function signedPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
}

/**
 * Etykiety definicji, które backend zwraca KODEM (`placements_definition`,
 * `hit_ratio_definition`).
 *
 * Nieznany kod renderujemy dosłownie zamiast chować — trzy różne „placementy"
 * w jednej aplikacji to jest ta pomyłka, którą ta powierzchnia zamyka, więc
 * milczący kafel byłby powrotem do punktu wyjścia.
 */
const DEFINITION_PL: Record<string, string> = {
  first_hired_per_candidate_job:
    "Placement = PIERWSZE „zatrudniony” dla pary kandydat × rekrutacja. " +
    "Powrót kandydata do etapu nie liczy się drugi raz.",
  first_hired_per_candidate_and_job:
    "Placement = PIERWSZE „zatrudniony” dla pary kandydat × rekrutacja. " +
    "Powrót kandydata do etapu nie liczy się drugi raz.",
  closed_jobs_with_at_least_one_placement:
    "Hit ratio = odsetek rekrutacji ZAMKNIĘTYCH w tym oknie, w których ktoś " +
    "został zatrudniony (zatrudnienie liczy się kiedykolwiek — ofertę " +
    "zamkniętą w lipcu zwykle obsadzono wcześniej).",
};

export function definitionText(code: string | null | undefined): string | null {
  if (!code) return null;
  return DEFINITION_PL[code] ?? `Definicja z serwera: ${code}`;
}

/** Jednolinijkowy podpis „co ten kafel liczy”. */
export function DefinitionNote({ children }: { children: ReactNode }) {
  if (!children) return null;
  return (
    <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span>{children}</span>
    </p>
  );
}
