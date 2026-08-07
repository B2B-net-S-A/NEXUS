import api from "@/lib/api"
import type {
  DashboardPeriod,
  DashboardPreset,
} from "@/lib/dashboard-presets"

export type DashboardQualityStatus =
  | "complete"
  | "partial"
  | "stale"
  | "unavailable"
export type DashboardSeverity = "info" | "warning" | "critical"

export interface DashboardScope {
  kind: "organization" | "recruitment_org" | "delivery_clients" | "self"
  user_id: number | null
  client_ids: number[]
  tac_user_ids: number[]
  operator_user_ids: number[]
  client_tac_pairs: Array<{
    client_id: number
    tac_user_id: number
  }>
}

export interface DashboardSectionQuality {
  status: DashboardQualityStatus
  warnings: string[]
  source_watermarks: Record<string, string>
}

export interface DashboardDataQuality {
  status: DashboardQualityStatus
  warnings: string[]
  source_watermarks: Record<string, string>
  sections: Record<string, DashboardSectionQuality>
}

export interface DashboardKpi {
  value: string | number | null
  unit: "count" | "percent" | "hours" | "PLN" | "fraction" | "status"
  quality: DashboardQualityStatus
  target: string | number | null
  comparison: string | number | null
  definition: string
  drilldown_href: string | null
}

export interface DashboardAlert {
  id: string
  kind: string
  severity: DashboardSeverity
  title: string
  description: string | null
  source: string
  occurred_at: string | null
  due_at: string | null
  entity_type: string | null
  entity_id: number | null
  href: string | null
}

export interface DashboardQueueItem {
  id: string
  kind: string
  priority: number
  title: string
  subtitle: string | null
  source: string
  due_at: string | null
  entity_type: string | null
  entity_id: number | null
  href: string | null
  action_label: string | null
  version: number | null
}

interface DashboardResponseBase<TData> {
  schema_version: "2"
  generated_at: string
  scope: DashboardScope
  data_quality: DashboardDataQuality
  data: TData
}

interface DashboardDataBase {
  kpis: Record<string, DashboardKpi>
  alerts: DashboardAlert[]
  queue: DashboardQueueItem[]
}

export interface AdminOpsBoardRow {
  id: string
  severity: DashboardSeverity
  domain: string
  signal: string
  last_success_at: string | null
  owner: string | null
  next_action_href: string | null
}

export interface AdminOpsDashboardData extends DashboardDataBase {
  operations_board: AdminOpsBoardRow[]
}

export interface DeliveryRiskBoardRow {
  client_id: number
  client_name: string
  job_id: number
  job_title: string
  priority: string
  open_vacancies: number
  tac_user_id: number | null
  age_days: number
  first_recommendation_at: string | null
  risk: DashboardSeverity
  next_action_href: string
}

export interface DeliveryLeadDashboardData extends DashboardDataBase {
  risk_board: DeliveryRiskBoardRow[]
}

export interface RecruitmentTeamBoardRow {
  user_id: number
  user_name: string
  roles: string[]
  status: string
  verification_capacity: number
  verification_target: number
  assignment_count: number
  carry_over_count: number
  urgent_carry_over_count: number
  blocker_count: number
}

export interface HeadOfRecruitmentDashboardData extends DashboardDataBase {
  team_board: RecruitmentTeamBoardRow[]
}

export type MyWorkDashboardData = DashboardDataBase

export interface FinanceExceptionBoardRow {
  id: string
  severity: DashboardSeverity
  kind: string
  client_id: number | null
  client_name: string | null
  contract_id: number | null
  invoice_id: number | null
  invoice_number: string | null
  amount: string | null
  currency: string | null
  due_at: string | null
  next_action_href: string | null
}

export interface FinanceDashboardData extends DashboardDataBase {
  tab: "operations" | "executive"
  exceptions_board: FinanceExceptionBoardRow[]
}

export interface DashboardV2ResponseMap {
  "admin-ops": DashboardResponseBase<AdminOpsDashboardData>
  "delivery-lead": DashboardResponseBase<DeliveryLeadDashboardData>
  "head-of-recruitment": DashboardResponseBase<HeadOfRecruitmentDashboardData>
  "my-work": DashboardResponseBase<MyWorkDashboardData>
  finance: DashboardResponseBase<FinanceDashboardData>
}

const ENDPOINTS: Record<DashboardPreset, string> = {
  "admin-ops": "/api/dashboard/v2/admin-ops",
  "delivery-lead": "/api/dashboard/v2/delivery-lead",
  "head-of-recruitment": "/api/dashboard/v2/head-of-recruitment",
  "my-work": "/api/dashboard/v2/my-work",
  finance: "/api/dashboard/v2/finance",
}

export type FinanceDashboardTab = "operations" | "executive"

// ── Statystyki rekrutacji (sekcja wspólna wszystkich presetów) ──────────────
// Lustro RecruitmentStats* z backend/app/schemas/dashboard_v2.py.
// Pod-bloki są null-owalne: awaria źródła = null + sekcja unavailable
// w data_quality — nigdy fabrykowane zera.

export interface RecruitmentStatsPeriod {
  kind: string
  start: string
  end: string
  timezone: string
}

export interface RecruitmentStatsKpis {
  verifications: DashboardKpi
  recommendations: DashboardKpi
  interviews: DashboardKpi
  acceptances: DashboardKpi
  placements: DashboardKpi
}

export interface RecruitmentTeamTableRow {
  user_id: number
  name: string
  role: string
  verifications: number
  recommendations: number
  interviews: number
  acceptances: number
  placements: number
  cv_to_base: number
  precision_pct: number | null
  precision_verified_30d: number
  precision_sent_30d: number
}

export interface RecruitmentTeamTableTotals {
  verifications: number
  recommendations: number
  interviews: number
  acceptances: number
  placements: number
  cv_to_base: number
  precision_pct: number | null
  people: number
}

export interface RecruitmentTeamTable {
  precision_target_pct: number
  rows: RecruitmentTeamTableRow[]
  totals: RecruitmentTeamTableTotals
}

export interface RecruitmentFunnelConversions {
  verified_to_recommendation_pct: number | null
  recommendation_to_interview_pct: number | null
  interview_to_acceptance_pct: number | null
  acceptance_to_placement_pct: number | null
  interview_to_placement_pct: number | null
  overall_pct: number | null
}

export interface CompetitionRankingEntry {
  rank: number
  user_id: number
  name: string
  metric_value: number
  role: string | null
  hit_ratio: number | null
  prize_pln: number | null
  excluded: boolean
  qualified: boolean | null
  placements: number | null
  interviews: number | null
  recommendations: number | null
  verifications: number | null
  precision_pct: number | null
  required_verifications: number | null
  disqualification_reasons: string[]
}

export interface RecruitmentQuarterlyLeague {
  period: string
  days_remaining: number
  points_formula: Record<string, number>
  prizes_pln: Record<string, number>
  requirement: string
  top3: CompetitionRankingEntry[]
  full_ranking: CompetitionRankingEntry[]
}

export interface RecruitmentMonthlyRace {
  requirements: string[]
  ranking: CompetitionRankingEntry[]
  excluded_user_ids: number[]
  qualified_leader_user_id: number | null
}

export interface RecruitmentMonthlyRaces {
  period: string
  days_remaining: number
  prize_amount_pln: number
  prize_name: string
  recommendations: RecruitmentMonthlyRace
  placements: RecruitmentMonthlyRace
}

export interface RecruitmentHallOfFameHistoryEntry {
  rank: number
  user_id: number
  name: string
  metric_value: number | null
  points: number | null
  prize_pln: number | null
}

export interface RecruitmentHallOfFameHistoryPeriod {
  period: string
  top3: RecruitmentHallOfFameHistoryEntry[]
}

export interface RecruitmentHallOfFame {
  all_time: CompetitionRankingEntry[]
  history: RecruitmentHallOfFameHistoryPeriod[]
}

export interface RecruitmentLinkedInRow {
  user_id: number
  name: string
  role: string
  cv_added: number
  messages_sent: number
  responses_received: number
  response_rate: number
  cv_response_rate: number
  days_reported: number
}

export interface RecruitmentLinkedInTotals {
  cv_added: number
  messages_sent: number
  responses_received: number
  response_rate: number
  cv_response_rate: number
  active_users: number
}

export interface RecruitmentLinkedIn {
  date_from: string
  date_to: string
  per_user: RecruitmentLinkedInRow[]
  totals: RecruitmentLinkedInTotals
}

export interface RecruitmentTrendMonth {
  month: string
  verifications: number
  recommendations: number
  interviews: number
  acceptances: number
  placements: number
}

export interface RecruitmentTrend {
  months: RecruitmentTrendMonth[]
}

export interface RecruitmentStatsData {
  period: RecruitmentStatsPeriod
  kpis: RecruitmentStatsKpis
  team_table: RecruitmentTeamTable | null
  conversions: RecruitmentFunnelConversions | null
  quarterly_league: RecruitmentQuarterlyLeague | null
  monthly_races: RecruitmentMonthlyRaces | null
  hall_of_fame: RecruitmentHallOfFame | null
  linkedin: RecruitmentLinkedIn | null
  trend: RecruitmentTrend | null
}

export type RecruitmentStatsResponse =
  DashboardResponseBase<RecruitmentStatsData>

export async function getRecruitmentStats(
  period: DashboardPeriod,
): Promise<RecruitmentStatsResponse> {
  const response = await api.get<RecruitmentStatsResponse>(
    "/api/dashboard/v2/recruitment-stats",
    { params: { period } },
  )
  return response.data
}

export async function getDashboardV2<Preset extends DashboardPreset>(
  preset: Preset,
  options: {
    period: DashboardPeriod
    financeTab?: FinanceDashboardTab
  },
): Promise<DashboardV2ResponseMap[Preset]> {
  const params =
    preset === "admin-ops"
      ? undefined
      : {
          period: options.period,
          ...(preset === "finance"
            ? { tab: options.financeTab ?? "operations" }
            : {}),
        }
  const response = await api.get<DashboardV2ResponseMap[Preset]>(
    ENDPOINTS[preset],
    { params },
  )
  return response.data
}
