/**
 * „Ruchy" okna „Historia i czat" — ostatni ruch każdej osoby, policzony
 * z kolumn kanbana, które strona rekrutacji i tak już ma.
 *
 * Backend nie ma dziś dziennika ruchów PER REKRUTACJA: historia etapów jest
 * dostępna tylko dla pary kandydat × rekrutacja
 * (`GET /api/pipeline/history/{candidate_id}/{job_id}`), a odpytanie jej dla
 * każdej osoby dawałoby N żądań na otwarcie okna. Tablica niesie za to
 * `days_in_stage`, czyli „kiedy osoba weszła na OBECNY etap". Lista jest więc
 * uczciwie podpisana jako ostatni ruch każdej osoby — nie pełny dziennik —
 * i nie podaje autora ruchu, bo tablica go nie zna.
 */

import {
  columnLabel,
  type KanbanColumn,
} from "@/components/v2/pages/kanban-shared";

export interface RecruitmentMoveEntry {
  key: string;
  candidateId: number;
  fullName: string;
  stageLabel: string;
  /** Dni od wejścia na obecny etap; `null` = tablica nie podała. */
  daysInStage: number | null;
}

export function latestMovesFromKanban(
  columns: readonly KanbanColumn[],
): RecruitmentMoveEntry[] {
  const entries: RecruitmentMoveEntry[] = [];
  for (const column of columns) {
    for (const item of column.items) {
      const fullName = [item.name, item.lastname].filter(Boolean).join(" ").trim();
      entries.push({
        key: `${item.id}`,
        candidateId: item.candidate_id,
        fullName: fullName || `Kandydat #${item.candidate_id}`,
        stageLabel: columnLabel(column),
        daysInStage:
          typeof item.days_in_stage === "number" ? item.days_in_stage : null,
      });
    }
  }
  // Najświeższe ruchy na górze; osoby bez liczby dni na końcu — brak danych
  // to nie „dziś".
  return entries.sort((a, b) => {
    if (a.daysInStage == null && b.daysInStage == null) return 0;
    if (a.daysInStage == null) return 1;
    if (b.daysInStage == null) return -1;
    return a.daysInStage - b.daysInStage;
  });
}

/** `0` → „dziś", `1` → „wczoraj", `5` → „5 dni temu". */
export function formatDaysAgo(days: number | null): string {
  if (days == null) return "—";
  if (days <= 0) return "dziś";
  if (days === 1) return "wczoraj";
  return `${days} dni temu`;
}
