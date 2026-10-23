/**
 * Tabele osób w Insights (Zespół → Ludzie, „Performance per osoba”):
 * sortowanie po kolumnie i wiersz zbiorczy „Byli pracownicy”.
 *
 * Czysta logika bez Reacta — komponenty tylko podpinają klik nagłówka
 * i przełącznik „Pokaż byłych pracowników” (prośba z zespołu, 19.10.2026).
 */

import type { InsightsDlPortfolioLead } from "@/lib/insights-api";
import type { TeamPeopleRow } from "@/lib/insights-team-api";

export type SortDirection = "asc" | "desc";

export interface ColumnSort<Key extends string> {
  key: Key;
  dir: SortDirection;
}

/** Wartość komórki do porównania; `null` = brak wartości („—”). */
export type SortValue = number | string | null;

/**
 * Następny stan sortowania po kliknięciu nagłówka `key`.
 *
 * Ta sama kolumna odwraca kierunek. Nowa kolumna liczbowa zaczyna od
 * malejącej (najwyższe u góry), kolumna opisowa (`ascFirst`) od A do Z.
 */
export function nextColumnSort<Key extends string>(
  current: ColumnSort<Key> | null,
  key: Key,
  ascFirst: (key: Key) => boolean,
): ColumnSort<Key> {
  if (current && current.key === key) {
    return { key, dir: current.dir === "desc" ? "asc" : "desc" };
  }
  return { key, dir: ascFirst(key) ? "asc" : "desc" };
}

function compareValues(a: Exclude<SortValue, null>, b: Exclude<SortValue, null>): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), "pl");
}

/**
 * Sortuje wiersze po wartości kolumny.
 *
 * Brak wartości (`null`) stoi na końcu W OBU kierunkach — reguła stoi ponad
 * mnożnikiem kierunku, bo inaczej „malejąco” wynosiłoby brak danych na
 * szczyt kolumny. Remis zawsze po nazwisku rosnąco (wiersz bez nazwiska
 * przegrywa), żeby kolejność osób z równym wynikiem nie skakała między
 * renderami.
 */
export function sortRowsByColumn<Row>(
  rows: readonly Row[],
  value: (row: Row) => SortValue,
  dir: SortDirection,
  nameOf: (row: Row) => string | null | undefined,
): Row[] {
  const factor = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const va = value(a);
    const vb = value(b);
    if (va === null || vb === null) {
      if (va !== vb) return va === null ? 1 : -1;
    } else {
      const primary = compareValues(va, vb) * factor;
      if (primary !== 0) return primary;
    }
    const na = nameOf(a) || null;
    const nb = nameOf(b) || null;
    if (na === null || nb === null) {
      return na === nb ? 0 : na === null ? 1 : -1;
    }
    return na.localeCompare(nb, "pl");
  });
}

/**
 * Dzieli wiersze na listę osób i byłych pracowników (konto wyłączone,
 * `is_active === false` — ten sam sygnał co w Lidze i celach).
 *
 * `showFormer` = byli wracają na listę jako zwykłe wiersze, a zbiór byłych
 * jest pusty (wiersza zbiorczego wtedy nie ma).
 */
export function splitFormerEmployees<Row extends { is_active: boolean }>(
  rows: readonly Row[],
  showFormer: boolean,
): { people: Row[]; former: Row[] } {
  if (showFormer) return { people: [...rows], former: [] };
  return {
    people: rows.filter((row) => row.is_active),
    former: rows.filter((row) => !row.is_active),
  };
}

export interface FormerEmployeesSummary<Key extends string> {
  count: number;
  /** Imiona i nazwiska w kolejności alfabetycznej — jedna linia w wierszu. */
  names: string[];
  sums: Record<Key, number>;
}

/**
 * Wiersz „Byli pracownicy (N)”: nazwiska i sumy kolumn liczbowych.
 * Sumy firmy się nie zmieniają — liczby byłych przechodzą tu z ich wierszy.
 * Brak byłych = `null` (wiersza nie ma).
 */
export function summarizeFormerEmployees<Row, Key extends string>(
  rows: readonly Row[],
  nameOf: (row: Row) => string | null | undefined,
  columns: Record<Key, (row: Row) => number>,
): FormerEmployeesSummary<Key> | null {
  if (rows.length === 0) return null;
  const sums = {} as Record<Key, number>;
  for (const key of Object.keys(columns) as Key[]) {
    sums[key] = rows.reduce<number>((total, row) => total + columns[key](row), 0);
  }
  const names = rows
    .map((row) => nameOf(row)?.trim() || "Nieznana osoba")
    .sort((a, b) => a.localeCompare(b, "pl"));
  return { count: rows.length, names, sums };
}

// ─────────────────────────────────────────────────────────────────────────────
// Zespół → Ludzie: kolumny obu zakładek.
// ─────────────────────────────────────────────────────────────────────────────

export type TeamPeopleSortKey =
  | "name"
  | "verifications_per_workday"
  | "recommendations"
  | "interviews"
  | "acceptances"
  | "placements"
  | "in_flight"
  | "precision_pct"
  | "placements_delta";

/** Wartość kolumny „Rekruterzy”; „vs poprzednio” = różnica placementów. */
export function teamPeopleSortValue(
  row: TeamPeopleRow,
  key: TeamPeopleSortKey,
): SortValue {
  switch (key) {
    case "name":
      return row.name || null;
    case "placements_delta":
      return row.placements - row.previous_placements;
    // Pola od 22.10.2026 — w odpowiedzi sprzed wdrożenia ich nie ma.
    case "acceptances":
      return row.acceptances ?? null;
    case "in_flight":
      return row.in_flight ?? null;
    default:
      return row[key];
  }
}

export type DlLeadSortKey =
  | "name"
  | "requests"
  | "open_requests"
  | "placements"
  | "hit_ratio";

/** Wartość kolumny „Delivery Leadzi”. */
export function dlLeadSortValue(
  lead: InsightsDlPortfolioLead,
  key: DlLeadSortKey,
): SortValue {
  return key === "name" ? lead.dl_name || null : lead[key];
}

/** Kolumna z nazwiskiem otwiera się od A do Z, liczby od najwyższej. */
export function isNameColumn(key: string): boolean {
  return key === "name";
}
