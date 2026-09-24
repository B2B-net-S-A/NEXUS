import type { ImportRow } from "@/lib/api/orderGroups";

/**
 * Stan wiersza importu MD do koloru i liczników nagłówka (audyt 24.09.2026,
 * U14). Każdy wiersz ma DOKŁADNIE jeden stan, więc liczniki nad tabelą sumują
 * się do liczby wierszy i zgadzają z etykietami w kolumnie „Status”.
 *
 *  - `applied` — MD zeszły z puli,
 *  - `pending` — czeka na człowieka (kilka zamówień, przekroczenie puli),
 *  - `cost`    — nic z MD, ale faktura zeszła z zamówienia kosztowego,
 *  - `neutral` — osoba bez zamówienia MD w tym miesiącu (zwykły kontraktor
 *                okresowy) — to nie jest błąd, więc bez czerwieni,
 *  - `danger`  — numer z „Uwag”, którego nie da się rozliczyć, albo faktura,
 *                która nie trafiła na żadne zamówienie.
 *
 * Etykietę składa serwer (`status_label`); tu wyłącznie ton.
 */
export type ImportRowTone = "applied" | "pending" | "cost" | "neutral" | "danger";

export function importRowTone(row: ImportRow): ImportRowTone {
  if (row.status === "applied") return "applied";
  if (row.status === "needs_assignment" || row.status === "overflow") return "pending";
  if (row.cost_status === "applied") return "cost";
  if (row.status_reason) return "danger";
  if (row.cost_status != null) return "danger";
  // Wiersz z samą fakturą bez numeru zamówienia — kwota nigdzie nie zeszła.
  if (row.status === "cost_only") return "danger";
  return "neutral";
}

export type ImportRowToneCounts = Record<ImportRowTone, number>;

export function countImportRowTones(rows: ImportRow[]): ImportRowToneCounts {
  const counts: ImportRowToneCounts = {
    applied: 0,
    pending: 0,
    cost: 0,
    neutral: 0,
    danger: 0,
  };
  for (const row of rows) counts[importRowTone(row)] += 1;
  return counts;
}
