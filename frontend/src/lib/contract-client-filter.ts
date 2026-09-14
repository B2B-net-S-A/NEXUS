/**
 * Client-side matcher for the Contracts "Klient" picker.
 *
 * The picker loads the full client list once and filters in the browser. The
 * matcher is word-prefix based (not raw substring) so the list narrows visibly
 * from the very first typed letter: e.g. "po" surfaces only names whose start —
 * or one of whose words — begins with "po" (American Hearts of **Po**land,
 * Bank **Po**cztowy) instead of every mid-word occurrence (IPO**PE**MA,
 * Gas**po**l, Dek**po**l) that made short queries look unresponsive.
 */

export interface ClientRef {
  id: number;
  name: string;
}

const COMBINING_MARKS = new RegExp("[\\u0300-\\u036f]", "g");
// Separatorem słów jest KAŻDY znak, który nie jest literą ani cyfrą. Wąska
// lista (spacja / . , -) nie znała nawiasów, więc nazwa „[QA-E2E] Klient"
// miała pierwsze słowo „[qa" i nie dawała się znaleźć po „QA-E2E" (UAT M02-B02).
const WORD_SEPARATORS = /[^\p{L}\p{N}]+/u;

function words(folded: string): string[] {
  return folded.split(WORD_SEPARATORS).filter(Boolean);
}

/**
 * Diacritic-insensitive fold, including the Polish ł/Ł that NFD does not
 * decompose. Keeps matching responsive regardless of accents.
 */
export function foldText(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(COMBINING_MARKS, "")
    .replace(/ł/g, "l");
}

/**
 * Rank a client name against an already-folded query. Lower is better;
 * -1 = no match. 0 → the full name starts with the query (also after dropping
 * punctuation), 1 → every query word is a prefix of some word in the name.
 */
export function matchRank(name: string, foldedQuery: string): number {
  const folded = foldText(name);
  if (folded.startsWith(foldedQuery)) return 0;
  const nameWords = words(folded);
  const queryWords = words(foldedQuery);
  if (queryWords.length === 0) return -1;
  // Nazwa zaczyna się od zapytania po zdjęciu interpunkcji („[QA-E2E] Klient"
  // ↔ „qa-e2e"): wszystkie słowa zapytania poza ostatnim równe kolejnym słowom
  // nazwy, ostatnie — prefiks.
  const last = queryWords.length - 1;
  if (
    queryWords.length <= nameWords.length &&
    queryWords.every((word, i) =>
      i === last ? nameWords[i].startsWith(word) : nameWords[i] === word,
    )
  ) {
    return 0;
  }
  // Zapytanie wielowyrazowe („Klient Testowy") jest tokenizowane: KAŻDE słowo
  // zapytania musi być prefiksem jakiegoś słowa nazwy. Nadal bez dopasowań
  // w środku słowa — patrz nagłówek modułu.
  if (
    queryWords.every((word) =>
      nameWords.some((nameWord) => nameWord.startsWith(word)),
    )
  ) {
    return 1;
  }
  return -1;
}

/**
 * Filter + rank clients for the picker. An empty query returns the head of the
 * (already alphabetical) list. Name-prefix matches rank above word-prefix
 * matches; ties keep the input order (a stable sort over pre-sorted data).
 */
export function filterClients<T extends ClientRef>(
  clients: readonly T[],
  query: string,
  limit = 100,
): T[] {
  const q = foldText(query.trim());
  if (!q) return clients.slice(0, limit);
  return clients
    .map((client) => ({ client, rank: matchRank(client.name, q) }))
    .filter((entry) => entry.rank >= 0)
    .sort((a, b) => a.rank - b.rank)
    .slice(0, limit)
    .map((entry) => entry.client);
}
