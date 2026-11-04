/**
 * Eksport „Placementy” z listy Kontraktów — okres startu kontraktu.
 *
 * Backend: `GET /api/contracts/export/placements?start_from&start_to`
 * (`services/contract_placements_export.py`), ta sama bramka co „Eksport”.
 */

export interface PlacementsRange {
  from: string;
  to: string;
}

const pad = (value: number) => String(value).padStart(2, "0");

/** Bieżący miesiąc kalendarza firmy: od 1. do ostatniego dnia. */
export function defaultPlacementsRange(todayIso: string): PlacementsRange {
  const [year, month] = todayIso.split("-").map(Number);
  const lastDay = new Date(year, month, 0).getDate();
  return {
    from: `${year}-${pad(month)}-01`,
    to: `${year}-${pad(month)}-${pad(lastDay)}`,
  };
}

/** Komunikat błędu okresu albo `null`, gdy można pobierać. */
export function placementsRangeError(range: PlacementsRange): string | null {
  if (!range.from || !range.to) return "Podaj obie daty.";
  if (range.to < range.from) return "Data „do” jest wcześniejsza niż „od”.";
  return null;
}

export function placementsExportFilename(range: PlacementsRange): string {
  return `placementy-${range.from}-${range.to}.xlsx`;
}
