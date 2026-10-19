/**
 * D5 (19.10.2026): lista kandydatów oddziela osoby, które spełniają filtr
 * stawki / miasta / stażu Z DANYMI, od osób, które przeszły „na brak danych”
 * (`unknown_fields`, semantyka v2). Serwer stawia braki na końcu każdego
 * sortowania (`unknown_count_rank`), ale „Mile widziane” idą przed nimi —
 * wtedy braki bywają w środku listy i kreski nie rysujemy (`dividerIndex`
 * wymaga układu „najpierw z danymi, potem bez”).
 */
import type { CandidateFilters } from "@/lib/url-filters";

export interface UnknownRow {
  unknown_fields?: readonly string[] | null;
}

const hasUnknown = (row: UnknownRow): boolean => (row.unknown_fields?.length ?? 0) > 0;

/**
 * Indeks wiersza strony, nad którym stoi kreska „Bez stawki albo miasta…”,
 * albo `null`. Kreska jest tylko przy układzie „z danymi → bez danych”.
 * Na samej górze strony (indeks 0) — wyłącznie wtedy, gdy wiadomo, że
 * wszystkie osoby z danymi są na poprzednich stronach.
 */
export function dividerIndex(
  rows: readonly UnknownRow[],
  { offset, knownCount }: { offset: number; knownCount: number | null | undefined },
): number | null {
  const first = rows.findIndex(hasUnknown);
  if (first < 0) return null;
  if (!rows.slice(first).every(hasUnknown)) return null;
  if (first > 0) return first;
  return knownCount != null ? (knownCount === offset ? 0 : null) : offset === 0 ? 0 : null;
}

const FIELD_WORDS: Record<string, string> = {
  rate: "stawki",
  location: "miasta",
  experience: "stażu",
};

/** Pola z brakami w wierszach pod kreską, w stałej kolejności. */
export function unknownFieldsBelow(rows: readonly UnknownRow[], from: number): string[] {
  const seen = new Set<string>();
  for (const row of rows.slice(from)) for (const f of row.unknown_fields ?? []) seen.add(f);
  return ["rate", "location", "experience"].filter((f) => seen.has(f));
}

/** „Bez stawki albo miasta w profilu”. */
export function dividerTitle(fields: readonly string[]): string {
  const words = fields.map((f) => FIELD_WORDS[f]).filter(Boolean);
  return `Bez ${words.length ? words.join(" albo ") : "danych"} w profilu`;
}

/**
 * „Ukryj” na kresce: ukrywa braki stawki i miasta (D5), a gdy pod kreską są
 * braki stażu — także globalne „Ukryj osoby bez danych” (staż nie ma
 * własnego przełącznika).
 */
export function hideUnknownPatch(
  fields: readonly string[],
): Pick<CandidateFilters, "hideUnknownRate" | "hideUnknownLocation"> &
  Partial<Pick<CandidateFilters, "hideUnknown">> {
  return {
    hideUnknownRate: true,
    hideUnknownLocation: true,
    ...(fields.includes("experience") ? { hideUnknown: true } : {}),
  };
}

function fulfils(n: number): string {
  if (n === 1) return "spełnia";
  const mod10 = n % 10;
  const mod100 = n % 100;
  return mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? "spełniają" : "spełnia";
}

/**
 * „2 spełniają filtr · 23 bez danych” — gdy serwer podał liczbę osób z danymi
 * (`known_match_count`) i są osoby bez danych; inaczej `null` (wołający
 * pokazuje zwykłe „25 kandydatów”).
 */
export function knownSplitLabel(total: number, known: number | null | undefined): string | null {
  if (known == null || known >= total) return null;
  const missing = total - known;
  return `${known.toLocaleString("pl-PL")} ${fulfils(known)} filtr · ${missing.toLocaleString("pl-PL")} bez danych`;
}
