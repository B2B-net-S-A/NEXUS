/**
 * Numery stron pod listą — jak w Traffit: 1 2 3 … i ostatnia.
 *
 * Zwraca kolejne pozycje paska: numer strony albo `"gap"` (wielokropek).
 * Zawsze widać pierwszą i ostatnią stronę oraz sąsiadów bieżącej; przy
 * początku i końcu listy pięć stron z rzędu, żeby pasek nie skakał.
 * Najwyżej 7 pozycji — mieści się obok „Poprzednia / Następna” przy 1280 px.
 */
export type PageWindowItem = number | "gap";

const MAX_WITHOUT_GAPS = 7;
const EDGE_RUN = 5;

export function pageWindow(current: number, totalPages: number): PageWindowItem[] {
  const total = Math.floor(totalPages);
  if (!Number.isFinite(total) || total < 1) return [];
  const page = Math.min(Math.max(1, Math.floor(current) || 1), total);

  if (total <= MAX_WITHOUT_GAPS) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }
  if (page <= EDGE_RUN - 1) {
    return [...range(1, EDGE_RUN), "gap", total];
  }
  if (page >= total - (EDGE_RUN - 2)) {
    return [1, "gap", ...range(total - EDGE_RUN + 1, total)];
  }
  return [1, "gap", page - 1, page, page + 1, "gap", total];
}

function range(from: number, to: number): number[] {
  return Array.from({ length: to - from + 1 }, (_, i) => from + i);
}
