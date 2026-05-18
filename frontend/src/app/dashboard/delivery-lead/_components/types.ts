import type { HeroPodiumEntry } from "@/components/v2/gamification/HeroLigaMistrzow"

export interface DlRow {
  user_id: number
  name: string
  total_requests: number
  total_vacancies: number
  placements: number
  hit_ratio: number
  fill_rate: number
  avg_vacancies_per_request: number
  open_requests: number
  open_vacancies: number
  target_achieved: boolean
  clients: string[]
}

export interface DlOverall {
  total_requests: number
  total_vacancies: number
  total_placements: number
  total_open_requests: number
  total_open_vacancies: number
  avg_hit_ratio: number
  avg_fill_rate: number
  target_count: number
  dl_count: number
  hit_ratio_target_pct: number
}

export interface DlReport {
  period: string
  per_dl: DlRow[]
  overall: DlOverall
}

export interface MyDlReport {
  period: string
  me: DlRow
  rank: number
  total_dls: number
  team_overall: DlOverall
  leaderboard_top5: DlRow[]
}

export interface TrendPoint {
  month: string
  month_label: string
  requests: number
  vacancies: number
  placements: number
  hit_ratio: number
  fill_rate: number
}

export interface CompetitionResponse {
  type: string
  period: string
  top3: HeroPodiumEntry[]
  full_ranking: HeroPodiumEntry[]
  days_remaining: number | null
  quarterly_prizes_pln: Record<string, number> | null
  requirement: string | null
  target_pct: number | null
}

export interface DlClientsSummary {
  delivery_lead: { id: number; name: string }
  clients: Array<{ id: number; name: string; is_head: boolean }>
}

export type DlScope = "me" | "team"

export function hitRatioColor(value: number, target: number): string {
  if (value >= target) return "text-emerald-600 font-semibold"
  if (value >= target * 0.66) return "text-amber-600 font-medium"
  return "text-rose-600"
}

export function fillRateColor(value: number): string {
  if (value >= 30) return "text-emerald-600 font-semibold"
  if (value >= 15) return "text-amber-600 font-medium"
  return "text-rose-600"
}
