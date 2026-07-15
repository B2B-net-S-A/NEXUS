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
const WORD_SEPARATORS = /[\s/.,-]+/;

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
 * -1 = no match. 0 → the full name starts with the query, 1 → some word in the
 * name starts with the query.
 */
export function matchRank(name: string, foldedQuery: string): number {
  const folded = foldText(name);
  if (folded.startsWith(foldedQuery)) return 0;
  if (folded.split(WORD_SEPARATORS).some((word) => word.startsWith(foldedQuery))) {
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
