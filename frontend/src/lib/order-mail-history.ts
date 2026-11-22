/**
 * Historia automatycznej weryfikacji zamówień z maila — co zmienił każdy bieg.
 *
 * Wiersz historii powstaje przy każdej zmianie ODCISKU stanu kolejki, także gdy
 * zmieniła się tylko flaga karty dla Delivery Leada (wraca do zera w biegu po
 * karcie). Do 20.11.2026 każdy wiersz pokazywał same liczby „5 / 0 / 5”, więc
 * z historii nie dało się wyczytać, co się stało. Teraz wiersz mówi, co się
 * zmieniło względem poprzedniego, a biegi, w których zmienił się wyłącznie stan
 * powiadomień, są domyślnie zwinięte (z przełącznikiem — nic nie znika).
 */
import type { OrderMailRecheckEntry, OrderMailRecheckRun } from "@/lib/api/orderMail";

export const RECHECK_CATEGORY_LABEL: Record<string, string> = {
  awaiting_contract: "Czeka na podpis umowy",
  config: "Automatyczny zapis wyłączony",
  unrecognized: "Nie rozpoznano klienta",
  other: "Wymaga weryfikacji",
};

export function recheckEntryLabel(e: Pick<OrderMailRecheckEntry, "order_number" | "people" | "document_id">): string {
  return e.order_number ?? (e.people.length ? e.people.join(", ") : `Dokument #${e.document_id}`);
}

/** Co zmienił bieg względem poprzedniego (starszego) wiersza historii. */
export function runChanges(run: OrderMailRecheckRun, older: OrderMailRecheckRun | undefined): string[] {
  const before = new Map((older?.entries ?? []).map((e) => [e.document_id, e]));
  const now = new Set(run.entries.map((e) => e.document_id));
  const groups = new Map<string, string[]>();
  const add = (label: string, value: string) => groups.set(label, [...(groups.get(label) ?? []), value]);
  for (const e of run.entries) {
    const prev = before.get(e.document_id);
    const name = recheckEntryLabel(e);
    if (e.outcome === "applied") add("zapisano", name);
    else if (e.outcome === "error") add("błąd przy", name);
    else if (older && !prev) add("nowe do sprawdzenia", name);
    else if (prev && e.category && prev.category !== e.category) {
      add(`zmiana na „${(RECHECK_CATEGORY_LABEL[e.category] ?? e.category).toLowerCase()}”`, name);
    } else if (prev && prev.reasons.join("|") !== e.reasons.join("|")) add("zmiana powodu", name);
    if (e.alerted) add("karta do Delivery Leada", name);
  }
  for (const e of older?.entries ?? []) {
    if (!now.has(e.document_id) && e.outcome !== "applied") add("zeszło z kolejki", recheckEntryLabel(e));
  }
  return [...groups.entries()].map(([label, values]) => `${label}: ${[...new Set(values)].join(", ")}`);
}

export interface HistoryRow {
  run: OrderMailRecheckRun;
  changes: string[];
  /** Najstarszy wiersz w oknie historii — nie ma z czym go porównać. */
  oldest: boolean;
}

/**
 * Wiersze historii (od najnowszego, jak przysyła serwer) z opisem zmian.
 * `quiet` = wiersze, w których zmienił się tylko stan powiadomień.
 */
export function historyRows(runs: OrderMailRecheckRun[]): { rows: HistoryRow[]; quiet: number } {
  const rows = runs.map((run, idx) => ({
    run,
    changes: runChanges(run, runs[idx + 1]),
    oldest: idx === runs.length - 1 && runs.length > 1,
  }));
  return { rows, quiet: rows.filter((r) => isQuiet(r)).length };
}

export function isQuiet(row: HistoryRow): boolean {
  return !row.oldest && row.changes.length === 0 && row.run.entries.length > 0 && row.run.trigger !== "manual";
}
