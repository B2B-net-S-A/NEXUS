import axios from "axios"

import api from "@/lib/api"

export type PriorityWorkMode = "off" | "shadow" | "enforce"
export type PriorityRank = "A" | "B" | "C" | "D" | "E"
export type PriorityChannel = "database" | "linkedin" | "mixed"
export type PriorityPlanStatus = "draft" | "published" | "superseded"
export type PriorityMemberStatus = "active" | "paused"
export type PriorityBlockerStatus =
  | "pending"
  | "accepted"
  | "rejected"
  | "resolved"
export type PriorityExceptionStatus =
  | "approved"
  | "consumed"
  | "revoked"
  | "expired"

export const DEFAULT_PRIORITY_VERIFICATION_CAPACITY = 12

export function priorityCapacityFields(
  verificationTargets: number[],
  capacityReason?: string | null,
): {
  verification_capacity: number
  capacity_reason: string | null
} {
  const verificationCapacity = verificationTargets.reduce(
    (total, target) => total + target,
    0,
  )
  return {
    verification_capacity: verificationCapacity,
    capacity_reason:
      verificationCapacity === DEFAULT_PRIORITY_VERIFICATION_CAPACITY
        ? null
        : capacityReason?.trim() || null,
  }
}

export interface PriorityJobReference {
  id: number
  title: string
  client_name?: string | null
  competence_category_id?: number | null
  competence_category_ids?: number[]
}

export interface PriorityCandidateReference {
  id: number
  name: string
}

export interface PriorityAssignmentProgress {
  verifications: number
  recommendations: number
}

export interface PriorityBlocker {
  id: number
  assignment_id: number
  category: string
  note: string
  status: PriorityBlockerStatus
  decision_note?: string | null
  created_at?: string | null
  created_by_name?: string | null
}

export interface PriorityAssignment {
  id: number
  user_id?: number
  user_name?: string
  owner_user_id?: number | null
  effective_user_id?: number | null
  substitution?: { start_date: string; end_date: string } | null
  sourcing_pause_reason?: "favorite" | "manual" | null
  rank: PriorityRank | null
  position?: number
  channel: PriorityChannel
  job: PriorityJobReference
  demand_id?: number | null
  verification_target: number
  recommendation_target: number
  progress: PriorityAssignmentProgress
  gate_state: string
  cc_match?: boolean
  cc_exception_required?: boolean
  cc_exception_reason?: string | null
  extra_slot_reason?: string | null
  blocker?: PriorityBlocker | null
  blockers?: PriorityBlocker[]
}

export interface PriorityCarryOver {
  process_id: number
  state_version: number
  candidate: PriorityCandidateReference
  job: PriorityJobReference
  current_stage: string
  owner_user_id: number | null
  owner_name?: string | null
  urgency: string
  days_in_stage: number
}

export interface PriorityPlan {
  id: number
  version: number
  row_version: number
  status: PriorityPlanStatus
  effective_from?: string | null
  review_due_at: string | null
  published_at?: string | null
  note?: string | null
  mode?: PriorityWorkMode
  overdue?: boolean
  members?: PriorityPlanMemberSnapshot[]
}

export interface PriorityPlanAssignmentSnapshot {
  id: number
  demand_id: number
  job_id: number
  rank: PriorityRank | null
  position?: number
  channel: PriorityChannel
  verification_target: number
  recommendation_target: number
  competence_category_id?: number | null
  competence_matches: boolean
  cc_exception_required?: boolean
  cc_exception_reason?: string | null
  extra_slot_reason?: string | null
}

export interface PriorityPlanMemberSnapshot {
  id: number
  user_id: number
  status: PriorityMemberStatus
  verification_capacity?: number
  capacity_reason?: string | null
  paused_reason?: string | null
  extra_slots_reason?: string | null
  assignments: PriorityPlanAssignmentSnapshot[]
}

export interface PriorityDemand {
  id: number
  row_version: number
  job: PriorityJobReference
  requested_by_id?: number
  requested_by_name?: string | null
  status: string
  urgency: string
  expected_recommendations: number
  deadline?: string | null
  channel: PriorityChannel
  brief_ready: boolean
  note?: string | null
  covered_recommendations?: number
  assignments_count?: number
  assignments?: PriorityAssignment[]
}

export interface PriorityTeamMember {
  user_id: number
  user_name: string
  role: string
  roles?: string[]
  allowed_channels?: PriorityChannel[]
  competence_category_ids?: number[]
  status: PriorityMemberStatus
  verification_capacity?: number
  paused_reason?: string | null
  extra_slots_reason?: string | null
  capacity_reason?: string | null
  assignments: PriorityAssignment[]
  carry_over?: PriorityCarryOver[]
  carry_over_count?: number
  urgent_carry_over_count?: number
}

export interface CurrentPriorityWorkResponse {
  mode: PriorityWorkMode
  plan: PriorityPlan | null
}

export interface MyPriorityWorkResponse {
  mode: PriorityWorkMode
  plan: PriorityPlan | null
  assignments: PriorityAssignment[]
  carry_over: PriorityCarryOver[]
}

export interface TeamPriorityWorkResponse {
  mode: PriorityWorkMode
  plan: PriorityPlan | null
  members: PriorityTeamMember[]
  demands: PriorityDemand[]
  unowned_carry_over: PriorityCarryOver[]
  unowned_carry_over_count: number
  overdue: boolean
}

export interface JobPriorityWorkResponse {
  mode: PriorityWorkMode
  plan: PriorityPlan | null
  assignments: PriorityAssignment[]
  carry_over_count: number
  blockers: PriorityBlocker[]
}

export interface PriorityWorkConflict {
  code: "PRIORITY_WORK_LOCKED"
  action: string
  job_id: number
  active_plan_id: number | null
  reason: string
  next_action: string
  message: string
}

export interface PriorityDemandInput {
  job_id: number
  urgency: string
  expected_recommendations: number
  deadline?: string | null
  channel: PriorityChannel
  brief_ready: boolean
  note: string
}

export type PriorityDemandUpdate = Partial<PriorityDemandInput> & {
  expected_version: number
  status?: string
}

export interface PriorityAssignmentInput {
  job_id: number
  demand_id?: number | null
  rank: PriorityRank | null
  position?: number
  channel: PriorityChannel
  verification_target: number
  recommendation_target: number
  cc_match: boolean
  cc_exception_reason?: string | null
}

export interface PriorityException {
  id: number
  user_id: number
  job_id: number
  status: PriorityExceptionStatus
  reason: string
  valid_from: string
  expires_at: string
  consumed_at?: string | null
  consumed_candidate_id?: number | null
  consumed_process_id?: number | null
  origin_assignment_id?: number | null
}

export interface PriorityExceptionInput {
  user_id: number
  job_id: number
  reason: string
  valid_from: string
  expires_at: string
  origin_assignment_id?: number | null
}

export interface PriorityPlanMemberInput {
  user_id: number
  status: PriorityMemberStatus
  verification_capacity: number
  capacity_reason?: string | null
  paused_reason?: string | null
  extra_slots_reason?: string | null
  assignments: PriorityAssignmentInput[]
}

export interface PriorityWorkStatus {
  mode: PriorityWorkMode
  current_plan_id: number | null
  plan_overdue: boolean
  users_without_coverage: number
  unowned_carry_over: number
  eligibility_coverage_percent: number
  shadow_violation_count: number
  worker_heartbeat_at: string | null
  last_reconciled_at: string | null
  last_alert_sweep_at: string | null
  last_error: string | null
  metrics: Record<string, unknown>
}

export interface PriorityPlanUpdateInput {
  expected_version: number
  note?: string | null
  members: PriorityPlanMemberInput[]
}

export const priorityWorkQueryKeys = {
  all: ["priority-work"] as const,
  current: () => [...priorityWorkQueryKeys.all, "current"] as const,
  mine: () => [...priorityWorkQueryKeys.all, "mine"] as const,
  team: () => [...priorityWorkQueryKeys.all, "team"] as const,
  status: () => [...priorityWorkQueryKeys.all, "status"] as const,
  demands: () => [...priorityWorkQueryKeys.all, "demands"] as const,
  exceptions: () => [...priorityWorkQueryKeys.all, "exceptions"] as const,
  job: (jobId: number) =>
    [...priorityWorkQueryKeys.all, "job", jobId] as const,
}

export const priorityWorkApi = {
  getCurrent: () =>
    api
      .get<CurrentPriorityWorkResponse>("/api/priority-work/current")
      .then((response) => response.data),
  getMine: () =>
    api
      .get<MyPriorityWorkResponse>("/api/priority-work/mine")
      .then((response) => response.data),
  getTeam: () =>
    api
      .get<TeamPriorityWorkResponse>("/api/priority-work/team")
      .then((response) => response.data),
  getStatus: () =>
    api
      .get<PriorityWorkStatus>("/api/priority-work/status")
      .then((response) => response.data),
  listDemands: () =>
    api
      .get<PriorityDemand[]>("/api/priority-work/demands")
      .then((response) => response.data),
  createDemand: (payload: PriorityDemandInput) =>
    api
      .post<PriorityDemand>("/api/priority-work/demands", payload)
      .then((response) => response.data),
  updateDemand: (demandId: number, payload: PriorityDemandUpdate) =>
    api
      .patch<PriorityDemand>(
        `/api/priority-work/demands/${demandId}`,
        payload,
      )
      .then((response) => response.data),
  createDraft: (payload: {
    source_plan_id?: number
    note?: string | null
  }) =>
    api
      .post<PriorityPlan>("/api/priority-work/plans/draft", payload)
      .then((response) => response.data),
  updatePlan: (planId: number, payload: PriorityPlanUpdateInput) =>
    api
      .put<PriorityPlan>(`/api/priority-work/plans/${planId}`, payload)
      .then((response) => response.data),
  publishPlan: (planId: number, expectedVersion: number) =>
    api
      .post<PriorityPlan>(`/api/priority-work/plans/${planId}/publish`, {
        expected_version: expectedVersion,
      })
      .then((response) => response.data),
  getJobContext: (jobId: number) =>
    api
      .get<JobPriorityWorkResponse>(`/api/priority-work/jobs/${jobId}`)
      .then((response) => response.data),
  createBlocker: (
    assignmentId: number,
    payload: { category: string; note: string },
  ) =>
    api
      .post<PriorityBlocker>(
        `/api/priority-work/assignments/${assignmentId}/blockers`,
        payload,
      )
      .then((response) => response.data),
  updateBlocker: (
    blockerId: number,
    payload: {
      status: PriorityBlockerStatus
      decision_note?: string | null
    },
  ) =>
    api
      .patch<PriorityBlocker>(
        `/api/priority-work/blockers/${blockerId}`,
        payload,
      )
      .then((response) => response.data),
  handoffProcess: (
    processId: number,
    payload: {
      process_id: number
      new_owner_user_id: number
      reason: string
      expected_process_version: number
    },
  ) =>
    api
      .post<PriorityCarryOver>(
        `/api/priority-work/processes/${processId}/handoff`,
        payload,
      )
      .then((response) => response.data),
  listExceptions: (status?: PriorityExceptionStatus) =>
    api
      .get<PriorityException[]>("/api/priority-work/exceptions", {
        params: status ? { status } : undefined,
      })
      .then((response) => response.data),
  createException: (payload: PriorityExceptionInput) =>
    api
      .post<PriorityException>("/api/priority-work/exceptions", payload)
      .then((response) => response.data),
  revokeException: (exceptionId: number, reason: string) =>
    api
      .post<{ ok: boolean; id: number; status: PriorityExceptionStatus }>(
        `/api/priority-work/exceptions/${exceptionId}/revoke`,
        { reason },
      )
      .then((response) => response.data),
}

function isPriorityWorkConflict(value: unknown): value is PriorityWorkConflict {
  if (!value || typeof value !== "object") return false
  const candidate = value as Partial<PriorityWorkConflict>
  return (
    candidate.code === "PRIORITY_WORK_LOCKED" &&
    typeof candidate.message === "string" &&
    typeof candidate.reason === "string" &&
    typeof candidate.action === "string"
  )
}

export function extractPriorityWorkConflict(
  error: unknown,
): PriorityWorkConflict | null {
  if (!axios.isAxiosError(error)) return null
  const responseData: unknown = error.response?.data
  if (isPriorityWorkConflict(responseData)) return responseData

  if (
    responseData &&
    typeof responseData === "object" &&
    "detail" in responseData
  ) {
    const detail = (responseData as { detail?: unknown }).detail
    if (isPriorityWorkConflict(detail)) return detail
  }

  return null
}

const NEXT_ACTION_LABELS: Record<string, string> = {
  CONTACT_HEAD_OF_RECRUITMENT:
    "Skontaktuj się z Head of Recruitment, jeśli potrzebujesz wyjątku.",
  WORK_HIGHER_PRIORITY:
    "Najpierw uzupełnij target requestu o wyższym priorytecie.",
  RESOLVE_BLOCKER:
    "Zgłoś blocker albo dokończ pracę na wyższym priorytecie.",
}

export function priorityWorkErrorMessage(error: unknown): string | null {
  const conflict = extractPriorityWorkConflict(error)
  if (!conflict) return null
  const nextAction = NEXT_ACTION_LABELS[conflict.next_action]
  return nextAction
    ? `${conflict.message} ${nextAction}`
    : conflict.message
}

export function priorityPosition(item: { position?: number; rank?: PriorityRank | null }): number {
  return item.position ?? (item.rank ? item.rank.charCodeAt(0) - 64 : 1)
}
