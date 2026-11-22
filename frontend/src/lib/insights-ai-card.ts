// Insights → Zespół: udział CV do klienta, które przyszły z karty AI (22.11.2026).
// Definicja liczenia: `backend/app/services/insights_ai_card_cv_share.py`.

import { api } from "@/lib/api"

export interface AiCardCvWeek {
  week_start: string
  week_end: string
  cv_sent: number
  from_ai_card: number
  share_pct: number | null
  in_progress: boolean
}

export interface AiCardCvShare {
  window_from: string
  window_to: string
  target_pct: number
  /** Od najstarszego do bieżącego (ostatni ma `in_progress`). */
  weeks: AiCardCvWeek[]
}

export const AI_CARD_CV_QUERY_KEY = [
  "insights",
  "recruitment",
  "cv-from-ai-card",
] as const

export function fetchAiCardCvShare(): Promise<AiCardCvShare> {
  return api
    .get<AiCardCvShare>("/api/insights/recruitment/cv-from-ai-card")
    .then((r) => r.data)
}

/** Żaden tydzień okna nie miał wysyłki — pusty stan zamiast rzędu „—”. */
export function hasNoSends(data: AiCardCvShare): boolean {
  return data.weeks.every((week) => week.cv_sent === 0)
}
