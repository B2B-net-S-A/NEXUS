// Podsumowanie „Przelicz kategorie z COA” (F1, 15.11.2026) — testowane osobno.
import type { FrameworkRecomputeRow } from "@/lib/api/framework-rates";

export const RECOMPUTE_OUTCOME_LABEL: Record<string, string> = {
  updated: "Zmienione",
  unchanged: "Bez zmian",
  no_card: "Kategoria spoza cennika",
  no_label: "COA bez kategorii",
  no_coa: "Bez zapisanego COA",
  person_not_found: "Osoby nie ma w COA",
  person_ambiguous: "Kilka pasujących osób",
  unreadable: "Nieczytelny PDF",
  file_missing: "Brak pliku PDF",
  higher_limit_kept: "Limit wyższy niż cennik — sprawdź dopłatę",
  preview: "Do zmiany",
};

const ORDER = Object.keys(RECOMPUTE_OUTCOME_LABEL);

/** Liczba kontraktów per wynik, w stałej kolejności (zmienione najpierw). */
export function summarizeRecompute(rows: FrameworkRecomputeRow[]): [string, number][] {
  const counts = new Map<string, number>();
  for (const row of rows) counts.set(row.outcome, (counts.get(row.outcome) ?? 0) + 1);
  return [...counts.entries()].sort(
    (a, b) => (ORDER.indexOf(a[0]) + 100) % 100 - ((ORDER.indexOf(b[0]) + 100) % 100),
  );
}
