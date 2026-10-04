// Automat przydziału requestów (0371) — typy są lustrem
// `backend/app/api/request_board.py`, `request_work_states.py`
// i `competence_team.py`.

import { keepPreviousData, useQuery } from "@tanstack/react-query"

import api from "@/lib/api"
import type { RecruiterVia } from "@/lib/job-team"
import { DASHBOARD_SECTION_POLL_MS } from "@/lib/polling"
import type { PriorityLevel } from "@/lib/request-priority"
import type { VisibleState, WorkState } from "@/lib/request-work-state"

// ── Pulpit „Requesty i obłożenie" ───────────────────────────────────────────
//
// Pola dopisane 02.10.2026 (trzy role rekrutacji, propozycje automatu do
// akceptacji) są w typach opcjonalne: starszy backend ich nie oddaje, a ekran
// ma wtedy pokazać mniej, nie paść.

export interface BoardPerson {
  user_id: number
  name: string
  /** Propozycja automatu — czeka na akceptację, nikogo nie zobowiązuje. */
  proposed: boolean
  source: "auto" | "manual" | "owner"
  /** Skąd osoba jest przy rekrutacji (prowadzący, przypisanie, współpracownik). */
  via?: RecruiterVia
  /** Kto przypisał; `null` = nie wiadomo. */
  assigned_by_name?: string | null
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
  delivery_lead?: { id: number; name: string } | null
  priority_level?: PriorityLevel
  /** Data otwarcia requestu (ISO): `opened_at`, a bez niej data dodania. */
  opened_effective_at?: string | null
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
  /** Requesty, nad którymi osoba pracuje — bez propozycji. */
  count: number
  /** Propozycje automatu czekające na akceptację. */
  proposed?: number
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
  /** Kto patrzy — zakres kafelka („Moja kategoria”, „Moje jako DL”) liczy się z tego. */
  viewer?: { user_id: number; primary_category_id: number | null } | null
  /**
   * Początek okna „Zmiany od wczoraj” (ISO): ta sama godzina poprzedniego dnia
   * roboczego. `null`/brak = starszy backend — okno to ostatnia doba.
   */
  changes_since?: string | null
}

export const REQUEST_BOARD_QUERY_KEY = ["request-board"] as const

export function useRequestBoard(options: { enabled?: boolean } = {}) {
  return useQuery<RequestBoard>({
    queryKey: REQUEST_BOARD_QUERY_KEY,
    queryFn: async () => (await api.get<RequestBoard>("/api/request-board")).data,
    enabled: options.enabled ?? true,
    refetchInterval: DASHBOARD_SECTION_POLL_MS,
    staleTime: 30_000,
  })
}

export async function addBoardPerson(jobId: number, userId: number): Promise<void> {
  await api.post(`/api/request-board/jobs/${jobId}/people`, { user_id: userId })
}

/**
 * Zdejmuje osobę z roli „Rekruter” — ze wszystkich miejsc naraz (prowadzący,
 * przypisanie, współpracownik). Przy samej propozycji automatu oznacza
 * „odrzuć” i wymaga osoby, która rozstrzyga propozycje.
 */
export async function removeBoardPerson(jobId: number, userId: number): Promise<void> {
  await api.delete(`/api/request-board/jobs/${jobId}/people/${userId}`)
}

// ── Propozycje automatu: akceptacja, zmiana, odrzucenie ─────────────────────
// Decyduje admin albo Head of Recruitment (capability `request.proposal.decide`).

export type ProposalDecision = "accept" | "reject" | "replace"

export type ProposalDecisionBody =
  | { decision: "accept" | "reject" }
  | {
      decision: "replace"
      /** Kto ma pracować zamiast proponowanej osoby. */
      replacement_user_id: number
    }

export interface ProposalDecisionResult {
  decision: ProposalDecision
  /** Kto po decyzji pracuje nad requestem; `null` przy odrzuceniu. */
  assigned_user_id: number | null
}

/** 409 = propozycja jest już nieaktualna (serwer mówi to po polsku w `detail`). */
export async function decideProposal(
  jobId: number,
  userId: number,
  body: ProposalDecisionBody,
): Promise<ProposalDecisionResult> {
  return (
    await api.post<ProposalDecisionResult>(
      `/api/request-board/jobs/${jobId}/proposals/${userId}`,
      body,
    )
  ).data
}

export interface ProposalRef {
  job_id: number
  user_id: number
}

export interface ProposalAcceptResult extends ProposalRef {
  /** `gone` = propozycja przestała być aktualna; pozostałych to nie zatrzymuje. */
  status: "accepted" | "gone"
}

/** „Zaakceptuj wszystkie” — jedno żądanie, najwyżej 100 propozycji. */
export async function acceptProposals(
  items: readonly ProposalRef[],
): Promise<ProposalAcceptResult[]> {
  if (items.length === 0) return []
  const { data } = await api.post<{ results?: ProposalAcceptResult[] }>(
    "/api/request-board/proposals/accept",
    { items: items.map(({ job_id, user_id }) => ({ job_id, user_id })) },
  )
  return data.results ?? []
}

// ── Kategoria rekrutacji: kto w niej pracuje (informacyjnie) ────────────────

export interface CategoryRecruiter {
  user_id: number
  name: string
  email: string
  role: string | null
  is_primary: boolean
  /** 1 = pierwszy priorytet osoby, 2 = drugi. */
  priority: 1 | 2 | null
}

export const categoryRecruitersQueryKey = (categoryId: number) =>
  ["competence-category-recruiters", categoryId] as const

/** Aktywne osoby z kategorii kompetencji (`GET /api/competence-categories/{id}/recruiters`). */
export function useCategoryRecruiters(
  categoryId: number | null | undefined,
  options: { enabled?: boolean } = {},
) {
  return useQuery<CategoryRecruiter[]>({
    queryKey: categoryRecruitersQueryKey(categoryId ?? 0),
    queryFn: async () =>
      (
        await api.get<CategoryRecruiter[]>(
          `/api/competence-categories/${categoryId}/recruiters`,
        )
      ).data,
    enabled: (options.enabled ?? true) && categoryId != null,
    staleTime: 5 * 60_000,
  })
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
  /** Rekrutacja zamknięta — stanu pracy nie zmienia się, dopóki jej nie otworzą. */
  closed?: boolean
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
