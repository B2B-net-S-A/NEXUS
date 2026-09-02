import api from "@/lib/api"
import type { DashboardPreset } from "@/lib/dashboard-presets"

export type RecruitmentDashboardPreset = DashboardPreset

export interface RecruitmentOperationsPerson {
  id: number
  name: string
}

export interface RecruitmentOperationsLookup {
  id: number | null
  name: string
}

export interface RecruitmentOperationsStageCounts {
  sourcing: number
  verified: number
  recommended: number
  interview: number
  accepted: number
}

export interface RecruitmentOperationsFavorite {
  id: number
  name: string
  stage: string
}

export interface RecruitmentOperationsOwners {
  recruiter: RecruitmentOperationsPerson | null
  tac: RecruitmentOperationsPerson | null
  delivery_lead: RecruitmentOperationsPerson | null
  collaborators: RecruitmentOperationsPerson[]
}

export interface RecruitmentOperationsProcess {
  job_id: number
  title: string
  client: RecruitmentOperationsLookup
  competence_category: RecruitmentOperationsLookup | null
  candidate_count: number
  shared_candidate_count: number
  stage_counts: RecruitmentOperationsStageCounts
  favorite_candidate: RecruitmentOperationsFavorite | null
  owners: RecruitmentOperationsOwners
  href: string
}

export interface RecruitmentOperationsSummary {
  open_processes: number
  competence_categories: number
  active_candidates: number
  processes_without_favorite: number
  shared_candidates: number
  processes_with_shared_candidates: number
}

export interface RecruitmentOperationsCategory {
  id: number | null
  name: string
  total: number
  shared_candidates: number
  processes_with_shared_candidates: number
}

export interface RecruitmentOperationsListResponse {
  generated_at: string
  page: number
  page_size: number
  total: number
  summary: RecruitmentOperationsSummary
  categories: RecruitmentOperationsCategory[]
  items: RecruitmentOperationsProcess[]
}

export interface RecruitmentOperationsFavoriteOption {
  id: number
  name: string
  stage: string
}

export interface RecruitmentOperationsSimilarProcess {
  job_id: number
  title: string
  client: RecruitmentOperationsLookup
  competence_category: RecruitmentOperationsLookup | null
  similarity: number
  candidate_overlap: number
  href: string
}

export type RecruitmentOperationsSimilarityStatus =
  | "primary"
  | "extended"
  | "empty"
  | "degraded"

export interface RecruitmentOperationsDetailResponse {
  generated_at: string
  process: RecruitmentOperationsProcess
  can_edit_favorite: boolean
  favorite_options: RecruitmentOperationsFavoriteOption[]
  similarity_status: RecruitmentOperationsSimilarityStatus
  similar_processes: RecruitmentOperationsSimilarProcess[]
}

export interface RecruitmentOperationsListParams {
  page?: number
  page_size?: number
  q?: string
  category_id?: number | null
  mine_only?: boolean
}

export async function getRecruitmentOperations(
  preset: RecruitmentDashboardPreset,
  params: RecruitmentOperationsListParams = {},
): Promise<RecruitmentOperationsListResponse> {
  const response = await api.get<RecruitmentOperationsListResponse>(
    "/api/dashboard/v2/recruitment-operations",
    {
      params: {
        preset,
        page: params.page ?? 1,
        page_size: params.page_size ?? 50,
        ...(params.q ? { q: params.q } : {}),
        ...(typeof params.category_id === "number"
          ? { category_id: params.category_id }
          : {}),
        ...(params.mine_only ? { mine_only: true } : {}),
      },
    },
  )
  return response.data
}

export async function getRecruitmentOperation(
  preset: RecruitmentDashboardPreset,
  jobId: number,
): Promise<RecruitmentOperationsDetailResponse> {
  const response = await api.get<RecruitmentOperationsDetailResponse>(
    `/api/dashboard/v2/recruitment-operations/${jobId}`,
    { params: { preset } },
  )
  return response.data
}

export async function setRecruitmentOperationFavorite(
  preset: RecruitmentDashboardPreset,
  jobId: number,
  candidateId: number | null,
): Promise<RecruitmentOperationsFavorite | null> {
  const response = await api.put<RecruitmentOperationsFavorite | null>(
    `/api/dashboard/v2/recruitment-operations/${jobId}/favorite`,
    { candidate_id: candidateId },
    { params: { preset } },
  )
  return response.data
}
