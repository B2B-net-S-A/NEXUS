// „Do uzupełnienia” — kafelek z trzema listami zaległości (prośba Olafa,
// decyzje Artura 21.10.2026): umowy do zamknięcia, rekrutacje do dokończenia
// albo zamknięcia i wymagania do poprawy.
//
// Listy przychodzą z tego samego `GET /api/board-tasks` co panel „Czeka na
// Ciebie”. Gdy kafelek stoi na pulpicie, panel ich nie pokazuje; gdy go nie
// ma — zostają w panelu jak dotąd. Usunięcie kafelka nic więc nie gubi.

import type { BoardTasksResponse } from "@/lib/api/boardTasks"

export const TO_COMPLETE_TILE_TYPE = "to_complete"

export interface ToCompleteCounts {
  agreements: number
  jobs: number
  fixes: number
  total: number
}

export function toCompleteCounts(data: BoardTasksResponse): ToCompleteCounts {
  const agreements = data.agreements?.to_close.length ?? 0
  const jobs = (data.pending_jobs?.items.length ?? 0) + (data.unfinished_forms?.length ?? 0)
  const fixes = data.requirement_fixes?.length ?? 0
  return { agreements, jobs, fixes, total: agreements + jobs + fixes }
}

/** Kolejka panelu bez list, które stoją w kafelku „Do uzupełnienia”. */
export function withoutToCompleteLists(data: BoardTasksResponse): BoardTasksResponse {
  return {
    ...data,
    pending_jobs: null,
    unfinished_forms: null,
    // `[]`, nie `null`: o awarii liczenia mówi kafelek, nie panel.
    requirement_fixes: [],
    agreements: data.agreements ? { ...data.agreements, to_close: [] } : data.agreements,
  }
}
