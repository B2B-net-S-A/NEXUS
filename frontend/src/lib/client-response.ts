// Pulpit HoR/DL i Insights → Zespół: odpowiedź klienta i pierwsze CV po otwarciu.
// Definicje liczenia są w `backend/app/services/client_response_metrics.py`.

import { api } from "@/lib/api"

export interface ClientResponseClientRow {
  client_id: number
  client_name: string
  cv_in_progress: number
  cohort_cv: number
  responded_7d: number
  response_7d_pct: number | null
  oldest_waiting_workdays: number | null
}

export interface ClientResponseSummary {
  window_from: string
  window_to: string
  cohort_cv: number
  responded_7d: number
  response_7d_pct: number | null
  target_pct: number
  workdays: number
  excluded_mass_jobs: number
  excluded_mass_cv: number
  cv_in_progress: number
  clients: ClientResponseClientRow[]
}

export interface FirstCvWeek {
  week_start: string
  opened_jobs: number
  sla_eligible_jobs: number
  sla_within_jobs: number
  sla_pct: number | null
  median_first_cv_workdays: number | null
}

export interface FirstCvSummary {
  window_from: string
  window_to: string
  opened_jobs: number
  jobs_with_cv: number
  jobs_without_cv: number
  median_first_moved_workdays: number | null
  median_first_verified_workdays: number | null
  median_first_cv_workdays: number | null
  sla_workdays: number
  sla_eligible_jobs: number
  sla_within_jobs: number
  sla_pct: number | null
  weeks: FirstCvWeek[]
}

export interface ClientResponseBoard {
  response: ClientResponseSummary
  first_cv: FirstCvSummary
}

export const CLIENT_RESPONSE_QUERY_KEY = ["dashboard", "client-response"] as const
export const FIRST_CV_QUERY_KEY = ["insights", "recruitment", "first-cv"] as const

export function fetchClientResponseBoard(): Promise<ClientResponseBoard> {
  return api
    .get<ClientResponseBoard>("/api/dashboard/v2/client-response")
    .then((r) => r.data)
}

export function fetchFirstCv(): Promise<FirstCvSummary> {
  return api
    .get<FirstCvSummary>("/api/insights/recruitment/first-cv")
    .then((r) => r.data)
}

/** Procent bez zbędnego ułamka: `19,3%`, `40%`, a przy braku danych `—`. */
export function pctLabel(value: number | null): string {
  if (value === null) return "—"
  return `${value.toLocaleString("pl-PL", { maximumFractionDigits: 1 })}%`
}

/** „1 dzień rob.”, „2 dni rob.”, „1,5 dnia rob.”; przy braku danych `—`. */
export function workdaysLabel(value: number | null): string {
  if (value === null) return "—"
  if (value === 1) return "1 dzień rob."
  const text = value.toLocaleString("pl-PL", { maximumFractionDigits: 1 })
  return Number.isInteger(value) ? `${text} dni rob.` : `${text} dnia rob.`
}

/** Daty z API (`2026-10-12`) jako `12.10`, bez przesunięcia strefy. */
export function shortDate(iso: string): string {
  const [, month, day] = iso.split("-")
  return `${day}.${month}`
}

export function dateRangeLabel(from: string, to: string): string {
  return `${shortDate(from)}–${shortDate(to)}`
}
