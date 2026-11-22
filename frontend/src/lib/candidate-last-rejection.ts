/**
 * „Ostatnie odrzucenie” na liście kandydatów (06.11.2026, makiety:
 * https://claude.ai/artifact/HfjaZy1PzPFEaLNMayNNfx, wariant C).
 *
 * Pigułka „Odrzucenie” i pasek „Ostatnie odrzucenie w tym wyniku” czytają
 * jedną definicję z backendu (`app/services/candidate_last_rejection.py`):
 * najnowsze odrzucenie albo rezygnacja, które jest nadal stanem swojej pary.
 * Kolumny nie ma od 18.11.2026 (decyzja Artura): stary cytat wyglądał w niej na
 * dzisiejszy. Odrzucenie widać w linii „Ostatnio z osobą”
 * (`candidate-recent-facts.ts`), gdy jest wśród dwóch ostatnich informacji.
 *
 * Klucze filtra przychodzą z API: `r:<etykieta>` (powód ze słownika),
 * `t:<kategoria Traffita>` (import bez powodu), `none` (nic).
 */

import type { CandidateFilters, RejectionWho, RejectionWithinMonths } from "@/lib/url-filters";

export interface RejectionFacetItem {
  key: string;
  label: string;
  count: number;
}

export interface RejectionFacets {
  total: number;
  without_rejection: number;
  items: RejectionFacetItem[];
  who: Array<{ key: RejectionWho; count: number }>;
}

export const REJECTION_WHO_LABELS: Record<RejectionWho, string> = {
  client: "Klient",
  us: "My",
  candidate: "Kandydat",
};

export const REJECTION_MONTHS_OPTIONS: ReadonlyArray<{
  value: RejectionWithinMonths;
  label: string;
}> = [
  { value: 0, label: "Kiedykolwiek" },
  { value: 3, label: "3 mies." },
  { value: 12, label: "12 mies." },
];

export const TRAFFIT_KEY_PREFIX = "t:";
export const NO_REASON_KEY = "none";

/** Etykieta klucza bez odpowiedzi API (np. z adresu, zanim przyjdzie pasek). */
export function rejectionKeyLabel(key: string): string {
  if (key.startsWith("r:")) return key.slice(2);
  if (key.startsWith(TRAFFIT_KEY_PREFIX)) return `Traffit · ${key.slice(2)}`;
  if (key === "none") return "Bez powodu";
  return key;
}

type RejectionFilterFields = Pick<
  CandidateFilters,
  "rejectionKeys" | "rejectionBy" | "rejectionWithinMonths" | "rejectionExclude"
>;

export const NO_REJECTION_FILTER: RejectionFilterFields = {
  rejectionKeys: [],
  rejectionBy: [],
  rejectionWithinMonths: 0,
  rejectionExclude: false,
};

/** Ile ustawień siedzi w pigułce (licznik przycisku). */
export function rejectionFilterCount(f: RejectionFilterFields): number {
  return f.rejectionKeys.length + f.rejectionBy.length + (f.rejectionWithinMonths ? 1 : 0);
}

function rejectionWhat(f: RejectionFilterFields): string {
  const parts = [
    ...f.rejectionKeys.map(rejectionKeyLabel),
    ...f.rejectionBy.map((w) => REJECTION_WHO_LABELS[w]),
  ];
  const what = parts.length ? parts.join(", ") : "dowolne";
  const when = f.rejectionWithinMonths ? ` · ${f.rejectionWithinMonths} mies.` : "";
  return `${what}${when}`;
}

/**
 * Tekst chipa nad listą: „Odrzucenie: Brak doświadczenia, Klient · 3 mies.”
 * albo „bez: …” przy „Ukryj”. `null` = filtr nieustawiony.
 */
export function rejectionFilterSummary(f: RejectionFilterFields): string | null {
  if (rejectionFilterCount(f) === 0) return null;
  return `${f.rejectionExclude ? "Ukryte odrzucenie" : "Odrzucenie"}: ${rejectionWhat(f)}`;
}

/**
 * Klik w chip paska: pierwszy „pokaż tylko”, drugi „ukryj”, trzeci zdejmuje.
 * Pasek działa na jednym kluczu naraz w trybie, który już jest ustawiony —
 * wybór kilku powodów i „kto zakończył” zostaje w pigułce.
 */
export function cycleFacetKey(
  f: RejectionFilterFields,
  key: string,
): Partial<CandidateFilters> {
  const has = f.rejectionKeys.includes(key);
  if (!has) {
    return { rejectionKeys: [...f.rejectionKeys, key], rejectionExclude: f.rejectionExclude };
  }
  if (!f.rejectionExclude && f.rejectionKeys.length === 1) {
    return { rejectionExclude: true };
  }
  const rest = f.rejectionKeys.filter((k) => k !== key);
  return {
    rejectionKeys: rest,
    rejectionExclude: rest.length || f.rejectionBy.length ? f.rejectionExclude : false,
  };
}
