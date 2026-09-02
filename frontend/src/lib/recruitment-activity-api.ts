import api from "@/lib/api"

export type RecruitmentActivityMetric =
  | "verification"
  | "recommendation"
  | "interview"
  | "acceptance"
  | "placement"

export type RecruitmentActivityWindow = "day" | "month"

export interface RecruitmentActivityPerson {
  id: number
  name: string
  role: string
}

export interface RecruitmentActivityMetricCounts {
  metric: RecruitmentActivityMetric
  day: number | null
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
  job: { id: number; title: string; client_name: string; href: string }
  credited_user: RecruitmentActivityPerson | null
  reached_at: string
}

export interface RecruitmentActivityDetailResponse {
  generated_at: string
  metric: RecruitmentActivityMetric
  window: RecruitmentActivityWindow
  page: number
  page_size: number
  total: number
  items: RecruitmentActivityDetailItem[]
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
  filters: RecruitmentActivityFilters,
): Promise<RecruitmentActivitySummaryResponse> {
  const response = await api.get<RecruitmentActivitySummaryResponse>(
    "/api/dashboard/v2/recruitment-activity",
    { params: activityParams(filters) },
  )
  return response.data
}

export async function getRecruitmentActivityDetails(
  filters: RecruitmentActivityFilters & {
    metric: RecruitmentActivityMetric
    window: RecruitmentActivityWindow
    page?: number
    pageSize?: number
  },
): Promise<RecruitmentActivityDetailResponse> {
  const response = await api.get<RecruitmentActivityDetailResponse>(
    "/api/dashboard/v2/recruitment-activity/details",
    {
      params: {
        ...activityParams(filters),
        metric: filters.metric,
        window: filters.window,
        page: filters.page ?? 1,
        page_size: filters.pageSize ?? 25,
      },
    },
  )
  return response.data
}
