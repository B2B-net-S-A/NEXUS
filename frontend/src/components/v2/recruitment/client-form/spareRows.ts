/**
 * Wolne wiersze wzoru (23.11.2026) — to samo, co `client_form_structure.spare_ids`
 * na serwerze, liczone w oknie z wartości pól (wpis po zapisie robi z wolnego
 * wiersza wiersz do uzupełnienia, wyczyszczony wraca do wolnych).
 *
 * Wolny wiersz = wiersz bez nazwy ze wzoru („Wiersz N”), w którym nic nie
 * wpisano, i który nie jest pierwszym takim wierszem swojej tabeli. Kandydat
 * z jednymi studiami nie ma czego wpisać w wiersze 2–3 „Wykształcenia”.
 * Wiersz częściowo wypełniony to brak.
 */

import type { ClientFormField } from "@/lib/api/clientForms";

const CELL = /^t(\d+)\.r(\d+)\.c\d+$/;
const FREE_ROW = /^Wiersz \d+$/;

export function spareFieldIds(
  fields: ClientFormField[],
  values: Record<string, string>,
): Set<string> {
  const tables = new Map<string, string[][]>();
  let last: string | null = null;
  for (const field of fields) {
    const match = CELL.exec(field.id);
    if (field.kind !== "cell" || !match) continue;
    if (field.row_label && !FREE_ROW.test(field.row_label)) continue;
    const rows = tables.get(match[1]) ?? [];
    tables.set(match[1], rows);
    const row = `${match[1]}.${match[2]}`;
    if (row !== last) {
      rows.push([]);
      last = row;
    }
    rows[rows.length - 1].push(field.id);
  }
  const spare = new Set<string>();
  for (const rows of tables.values()) {
    for (const ids of rows.slice(1)) {
      if (ids.every((id) => (values[id] ?? "").trim() === "")) {
        for (const id of ids) spare.add(id);
      }
    }
  }
  return spare;
}
