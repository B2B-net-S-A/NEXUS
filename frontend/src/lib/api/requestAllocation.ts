// Automat przydziału requestów (0371) — typy są lustrem
// `backend/app/api/request_board.py`, `request_work_states.py`
// i `competence_team.py`.

import { keepPreviousData, useQuery } from "@tanstack/react-query"

import api from "@/lib/api"
import { DASHBOARD_SECTION_POLL_MS } from "@/lib/polling"
import type { VisibleState, WorkState } from "@/lib/request-work-state"

// ── Pulpit „Requesty i obłożenie" ───────────────────────────────────────────

export interface BoardPerson {
  user_id: number
  name: string
  role: "recruiter" | "sourcer"
  /** Propozycja automatu w trybie podglądu — nikogo nie zobowiązuje. */
  proposed: boolean
  source: "auto" | "manual" | "owner"
}

export interface BoardRequest {
  job_id: number
  title: string
  client_name: string | null
  category_id: number | null
  deadline: string | null
  sent: number
  champion: boolean
  people: BoardPerson[]
}

export interface BoardGroup {
  category_id: number | null
  name: string
  slug: string | null
  total: number
  searching: number
  champion: number
}

export interface LoadRequest {
  job_id: number
  title: string
  client_name: string | null
  deadline: string | null
  proposed: boolean
}

export interface LoadPerson {
  user_id: number
  name: string
  count: number
  leave_until: string | null
  requests: LoadRequest[]
}

export interface BoardChange {
  at: string
  kind: "assigned" | "released" | "champion"
  job_id: number
  title: string
  client_name: string | null
  user_name: string | null
  reason: string | null
}

export interface RequestBoard {
  mode: "off" | "shadow" | "auto"
  availability_known: boolean
  groups: BoardGroup[]
  requests: BoardRequest[]
  load: LoadPerson[]
  changes: BoardChange[]
}

export const REQUEST_BOARD_QUERY_KEY = ["request-board"] as const

export function useRequestBoard() {
  return useQuery<RequestBoard>({
    queryKey: REQUEST_BOARD_QUERY_KEY,
    queryFn: async () => (await api.get<RequestBoard>("/api/request-board")).data,
    refetchInterval: DASHBOARD_SECTION_POLL_MS,
    staleTime: 30_000,
  })
}

export async function addBoardPerson(
  jobId: number,
  userId: number,
  role: "recruiter" | "sourcer",
): Promise<void> {
  await api.post(`/api/request-board/jobs/${jobId}/people`, { user_id: userId, role })
}

export async function removeBoardPerson(jobId: number, userId: number): Promise<void> {
  await api.delete(`/api/request-board/jobs/${jobId}/people/${userId}`)
}

// ── „Porządek w requestach" ─────────────────────────────────────────────────

export interface ReviewRow {
  job_id: number
  title: string
  client_name: string | null
  delivery_lead_name: string | null
  deadline: string | null
  state: VisibleState
  state_label: string
  last_work_at: string | null
  last_cv_at: string | null
  sent_total: number
  applications_14d: number
  suggested_state: WorkState | null
  suggestion_reason: string
}

export interface ReviewResponse {
  tab: VisibleState
  counts: Record<VisibleState, number>
  rows: ReviewRow[]
  /** Wszystkich w zakładce (po filtrach) — lista idzie stronami. */
  total?: number
  has_more?: boolean
}

/** Pierwsza strona listy; „Pokaż więcej” podnosi limit o tyle samo. */
export const REVIEW_PAGE_SIZE = 200

export function reviewQueryKey(tab: VisibleState, mine: boolean, q: string, limit = REVIEW_PAGE_SIZE) {
  return ["request-work-states", tab, mine, q, limit] as const
}

export function useRequestReview(
  tab: VisibleState,
  mine: boolean,
  q: string,
  limit: number = REVIEW_PAGE_SIZE,
) {
  return useQuery<ReviewResponse>({
    queryKey: reviewQueryKey(tab, mine, q, limit),
    queryFn: async () =>
      (
        await api.get<ReviewResponse>("/api/request-work-states", {
          params: { tab, mine, q: q || undefined, limit },
        })
      ).data,
    staleTime: 15_000,
    // „Pokaż więcej” podnosi limit — bez tego lista znikałaby na czas odczytu.
    // Tylko w tej samej zakładce i z tymi samymi filtrami: wiersze innej
    // zakładki pod nagłówkiem nowej wyglądałyby jak jej treść.
    placeholderData: (previous, previousQuery) => {
      const key = previousQuery?.queryKey
      return key && key[1] === tab && key[2] === mine && key[3] === q
        ? keepPreviousData(previous)
        : undefined
    },
  })
}

export async function changeWorkStates(
  changes: { job_id: number; state: WorkState }[],
): Promise<{ changed: number[]; unchanged: number }> {
  return (await api.patch("/api/request-work-states", { changes })).data
}

// ── Panel „Kategorie kompetencji" ───────────────────────────────────────────

export interface TeamPerson {
  user_id: number
  name: string
  roles: string[]
  allocation_excluded: boolean
  assignment_id: number | null
}

export interface TeamCategory {
  id: number
  slug: string
  name: string
  requests_searching: number
  first: TeamPerson[]
  second: TeamPerson[]
}

export interface TeamRules {
  sourcer_threshold: number
  review_time: string
}

export interface CompetenceTeam {
  categories: TeamCategory[]
  unassigned: TeamPerson[]
  excluded: TeamPerson[]
  people: TeamPerson[]
  rules: TeamRules
}

export const COMPETENCE_TEAM_QUERY_KEY = ["competence-team"] as const

export function useCompetenceTeam() {
  return useQuery<CompetenceTeam>({
    queryKey: COMPETENCE_TEAM_QUERY_KEY,
    queryFn: async () => (await api.get<CompetenceTeam>("/api/competence-team")).data,
    staleTime: 15_000,
  })
}

export async function putTeamAssignment(
  userId: number,
  categoryId: number,
  priority: 1 | 2,
): Promise<void> {
  await api.put("/api/competence-team/assignments", {
    user_id: userId,
    competence_category_id: categoryId,
    priority,
  })
}

export async function deleteTeamAssignment(assignmentId: number): Promise<void> {
  await api.delete(`/api/competence-team/assignments/${assignmentId}`)
}

export async function setAllocationExcluded(
  userId: number,
  excluded: boolean,
): Promise<void> {
  await api.patch(`/api/competence-team/people/${userId}/allocation`, { excluded })
}

export async function putTeamRules(rules: TeamRules): Promise<TeamRules> {
  return (await api.put<TeamRules>("/api/competence-team/rules", rules)).data
}
