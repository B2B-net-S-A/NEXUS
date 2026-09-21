/**
 * Wspólne dane testowe widoku „rekrutacja = jedna tabela".
 *
 * Szablon odwzorowuje realny układ: wejście → screening → weryfikacja (dwa
 * etapy, w tym własny bez legacy enuma) → klient → umowa → terminale.
 */

import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";

let nextStageRowId = 1000;

export function item(candidateId: number, over: Partial<KanbanItem> = {}): KanbanItem {
  nextStageRowId += 1;
  return {
    id: nextStageRowId,
    candidate_id: candidateId,
    stage: "new",
    name: "Osoba",
    lastname: `Nr${candidateId}`,
    days_in_stage: 1,
    ...over,
  };
}

export function column(
  stage: string,
  stageDefId: number,
  name: string,
  items: KanbanItem[],
  over: Partial<KanbanColumn> = {},
): KanbanColumn {
  return {
    stage,
    stage_def_id: stageDefId,
    name,
    category: "internal",
    count: items.length,
    items: items.map((it) => ({ ...it, stage, stage_def_id: stageDefId })),
    ...over,
  };
}

/** Pełny szablon; `people` nadpisuje zawartość wybranych kolumn po `stage_def_id`. */
export function template(people: Record<number, KanbanItem[]> = {}): KanbanColumn[] {
  const at = (id: number) => people[id] ?? [];
  return [
    column("new", 1, "Nowy", at(1)),
    column("screening", 2, "Screening", at(2)),
    column("verified", 3, "Zweryfikowany", at(3)),
    // Własny etap wewnętrzny PO screeningu — bez legacy enuma raportuje `new`.
    column("new", 4, "Wysłać do Cpro", at(4)),
    column("cv_sent", 5, "CV Wysłane", at(5)),
    column("client_interview", 6, "Rozmowa z klientem", at(6), { category: "external" }),
    column("acceptance", 7, "Oferta", at(7), { category: "external" }),
    column("new", 8, "Umowa wysłana", at(8)),
    column("hired", 9, "Zatrudniony", at(9), { category: "terminal", terminal_type: "hired" }),
    column("rejected", 10, "Odrzucony", at(10), { category: "terminal", terminal_type: "rejected" }),
  ];
}
