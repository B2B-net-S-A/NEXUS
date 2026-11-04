// Które działy mapy cieplnej pokazać i gdzie postawić „bez działu” (czyste funkcje).
//
// Prod 20.10.2026 (Nordea): 67 działów ze „Struktury u klienta”, wszystkie bez
// źródeł, a cały sygnał (561 komórek) w „bez działu” na końcu tabeli 6350 px
// szerokiej. Decyzja Artura 20.10.2026: domyślnie tylko działy z sygnałem
// (przełącznik „Pokaż wszystkie działy”), „bez działu” na początku, gdy niesie
// więcej sygnału niż działy razem.

import type { HeatCell, HeatRow, MapDepartment } from "@/lib/api/care";

const hasSignal = (cell: HeatCell | null): boolean =>
  Boolean(cell && (cell.source_count > 0 || cell.open_jobs > 0));

export interface HeatColumns {
  /** Indeksy `departments` do pokazania, w kolejności serwera. */
  shown: number[];
  /** Działy bez sygnału schowane przełącznikiem. */
  hidden: number;
  /** „bez działu” jako pierwsza kolumna po technologii. */
  unassignedFirst: boolean;
}

export function heatColumns(
  departments: readonly MapDepartment[],
  rows: readonly HeatRow[],
  showAll: boolean,
): HeatColumns {
  const signal = departments.map(
    (dept, index) => dept.consultants > 0 || rows.some((row) => hasSignal(row.cells[index] ?? null)),
  );
  const shown = departments.map((_, index) => index).filter((index) => showAll || signal[index]);
  const inDepts = rows.reduce(
    (sum, row) => sum + row.cells.filter((cell) => hasSignal(cell)).length,
    0,
  );
  const unassigned = rows.filter((row) => hasSignal(row.unassigned)).length;
  return {
    shown,
    hidden: departments.length - shown.length,
    unassignedFirst: unassigned > inDepts,
  };
}
