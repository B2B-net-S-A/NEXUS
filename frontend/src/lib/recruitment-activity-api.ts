import api from "@/lib/api"

export type RecruitmentActivityMetric =
  | "verification"
  | "recommendation"
  | "interview"
  | "acceptance"
  | "placement"

/**
 * „week” = tydzień (od poniedziałku) wybranego dnia, jak cel „Rekomendacje
 * w tygodniu”; „range” = dni od–do włącznie (okres z paska Insights).
 */
export type RecruitmentActivityWindow = "day" | "week" | "month" | "range"

/** Gdzie para osoba × rekrutacja jest teraz (najnowszy wiersz etapu pary). */
export type RecruitmentActivityState =
  | "before_client"
  | "waiting"
  | "at_client"
  | "hired"
  | "rejected_by_client"
  | "ended"
  | "job_closed"

export interface RecruitmentActivityPerson {
  id: number
  name: string
  role: string
}

export interface RecruitmentActivityMetricCounts {
  metric: RecruitmentActivityMetric
  day: number | null
  /** Liczba okresu `period_start`–`period_end`: miesiąc albo wybrane od–do. */
  month: number
}

export interface RecruitmentActivityProgress {
  current: number
  target: number
  progress_pct: number
  remaining: number
}

export interface RecruitmentActivityComparison {
  metric: "verification" | "placement"
  personal_average: number | null
  team_average: number | null
  months: number
  period_start: string
  period_end: string
  people: number
}

export interface RecruitmentActivitySummaryResponse {
  generated_at: string
  day: string
  month: string
  /** Dni liczone w `metrics[].month` (włącznie); brak = serwer sprzed 29.10.2026. */
  period_start?: string | null
  period_end?: string | null
  scope: "person" | "team"
  can_view_team_details: boolean
  subject: RecruitmentActivityPerson | null
  selectable_people: RecruitmentActivityPerson[]
  metrics: RecruitmentActivityMetricCounts[]
  verification_progress: RecruitmentActivityProgress | null
  comparisons: RecruitmentActivityComparison[]
}

export interface RecruitmentActivityDetailItem {
  candidate: { id: number; name: string; href: string }
  job: {
    id: number
    /** Nazwa od klienta; ekran pokazuje `working_title ?? title` z numerem u klienta. */
    title: string
    working_title?: string | null
    client_reference?: string | null
    client_name: string
    href: string
  }
  credited_user: RecruitmentActivityPerson | null
  reached_at: string
  /** Kto kliknął etap — przy rekomendacji zwykle Delivery Lead. */
  moved_by?: RecruitmentActivityPerson | null
  state?: RecruitmentActivityState | null
  state_stage?: string | null
  state_since?: string | null
  state_reason?: string | null
  /** W ilu rekrutacjach ta sama osoba liczy się w tym okresie. */
  candidate_jobs?: number
}

export interface RecruitmentActivityDetailResponse {
  generated_at: string
  metric: RecruitmentActivityMetric
  window: RecruitmentActivityWindow
  page: number
  page_size: number
  /** Wierszy po filtrze stanu. */
  total: number
  items: RecruitmentActivityDetailItem[]
  // Pola listy „Kto się liczy” (17.10.2026) — opcjonalne, bo karta otwarta
  // przed wdrożeniem dostaje stary kształt odpowiedzi.
  period_start?: string | null
  period_end?: string | null
  scope?: "person" | "team" | "unattributed" | null
  subject?: RecruitmentActivityPerson | null
  people?: number
  moved_by_credited?: number
  states?: Partial<Record<RecruitmentActivityState, number>>
  state_filter?: RecruitmentActivityState | null
  /** Liczba okresu przed filtrem stanu — razem z `history_total`, jak licznik celów. */
  period_total?: number
  /**
   * Ile z `period_total` to tygodniowe wpisy DynaReportera (1.01–11.10.2026):
   * liczą się do wyniku, ale nie ma ich na liście (DynaReporter nie zapisywał kandydatów).
   */
  history_total?: number
}

interface RecruitmentActivityFilters {
  day: string
  month: string
  subjectUserId?: number | null
  teamScope?: boolean
}

function activityParams(filters: RecruitmentActivityFilters) {
  return {
    day: filters.day,
    month: `${filters.month}-01`,
    ...(typeof filters.subjectUserId === "number"
      ? { subject_user_id: filters.subjectUserId }
      : {}),
    ...(filters.teamScope ? { scope: "team" } : {}),
  }
}

export async function getRecruitmentActivitySummary(
  filters: RecruitmentActivityFilters & {
    /** Okres od–do (włącznie) zamiast miesiąca w liczbach kafli. */
    dateFrom?: string | null
    dateTo?: string | null
  },
): Promise<RecruitmentActivitySummaryResponse> {
  const response = await api.get<RecruitmentActivitySummaryResponse>(
    "/api/dashboard/v2/recruitment-activity",
    {
      params: {
        ...activityParams(filters),
        ...(filters.dateFrom && filters.dateTo
          ? { date_from: filters.dateFrom, date_to: filters.dateTo }
          : {}),
      },
    },
  )
  return response.data
}

export interface RecruitmentActivityDetailFilters extends RecruitmentActivityFilters {
  metric: RecruitmentActivityMetric
  window: RecruitmentActivityWindow
  /** Dla `window: "range"`: dni od–do włącznie (YYYY-MM-DD). */
  dateFrom?: string | null
  dateTo?: string | null
  /** Kamienie bez osoby z zasługą (tylko role z wglądem w zespół). */
  unattributed?: boolean
  state?: RecruitmentActivityState | null
  page?: number
  pageSize?: number
}

export async function getRecruitmentActivityDetails(
  filters: RecruitmentActivityDetailFilters,
): Promise<RecruitmentActivityDetailResponse> {
  const response = await api.get<RecruitmentActivityDetailResponse>(
    "/api/dashboard/v2/recruitment-activity/details",
    {
      params: {
        ...activityParams(filters),
        ...(filters.unattributed ? { scope: "unattributed" } : {}),
        ...(filters.window === "range" && filters.dateFrom && filters.dateTo
          ? { date_from: filters.dateFrom, date_to: filters.dateTo }
          : {}),
        ...(filters.state ? { state: filters.state } : {}),
        metric: filters.metric,
        window: filters.window,
        page: filters.page ?? 1,
        page_size: filters.pageSize ?? 25,
      },
    },
  )
  return response.data
}

export interface RecruitmentActivityTeamTotalsResponse {
  generated_at: string
  period_start: string
  period_end: string
  /** Liczba zespołu na etap — ta sama co `period_total` listy z `scope: "team"`. */
  totals: Partial<Record<RecruitmentActivityMetric, number>>
  /** Ile z liczby to wpisy DynaReportera (bez osób na liście). */
  history: Partial<Record<RecruitmentActivityMetric, number>>
}

/** Liczby zespołu za dni od–do (włącznie) dla kilku etapów jednym zapytaniem. */
export async function getRecruitmentActivityTeamTotals(filters: {
  dateFrom: string
  dateTo: string
  metrics: readonly RecruitmentActivityMetric[]
}): Promise<RecruitmentActivityTeamTotalsResponse> {
  const response = await api.get<RecruitmentActivityTeamTotalsResponse>(
    "/api/dashboard/v2/recruitment-activity/team-totals",
    {
      params: { date_from: filters.dateFrom, date_to: filters.dateTo, metric: [...filters.metrics] },
      paramsSerializer: { indexes: null },
    },
  )
  return response.data
}
