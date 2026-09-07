import { AxiosError } from "axios";

import api from "@/lib/api";

export const CONTACT_QUEUE_LIMIT = 20;

export type CandidateContactCaseStatus =
  | "unassigned"
  | "awaiting_capacity"
  | "queued"
  | "callback_due"
  | "cooldown"
  | "handoff_pending"
  | "blocked_no_phone"
  | "suppressed"
  | "completed"
  | "cancelled";

export type CandidateContactOutcome =
  | "connected"
  | "no_answer"
  | "callback_requested"
  | "wrong_number"
  | "do_not_contact";

export type CandidateContactOpportunityOutcome =
  | "interested"
  | "maybe"
  | "not_interested"
  | "not_presented";

export interface CandidateContactOwner {
  id: number;
  name: string;
}

export interface CandidateContactPerson {
  id: number;
  name?: string | null;
  lastname?: string | null;
  phone?: string | null;
  email?: string | null;
  current_role?: string | null;
  position?: string | null;
}

export interface CandidateContactOpportunity {
  id?: number;
  job_id: number;
  job_title: string;
  client_name?: string | null;
  owner?: CandidateContactOwner | null;
  outcome?: CandidateContactOpportunityOutcome | null;
  meeting_status?: string | null;
}

export interface CandidateContactSummary {
  id: number;
  status: CandidateContactCaseStatus;
  owner?: CandidateContactOwner | null;
  due_at?: string | null;
  callback_at?: string | null;
  attempts_in_cycle?: number;
  version: number;
}

export interface CandidateContactCase extends CandidateContactSummary {
  effective_owner?: { id: number; name: string } | null;
  substitution?: { start_date: string; end_date: string } | null;
  candidate: CandidateContactPerson;
  opportunities: CandidateContactOpportunity[];
}

export interface CandidateContactQueueResponse {
  items: CandidateContactCase[];
  utilization: {
    used: number;
    capacity: number;
  };
  next_cursor?: string | null;
}

export interface CandidateContactFeatureStatus {
  enabled: boolean;
  assignment_enabled: boolean;
  traffit_intake_enabled: boolean;
}

export interface CandidateContactOversightCounters {
  overdue: number;
  unassigned: number;
  awaiting_capacity: number;
  blocked_no_phone: number;
  ownerless_handoff?: number;
  reassigned_today?: number;
  traffit_lag_seconds?: number | null;
  traffit_status?: string | null;
  traffit_last_error?: string | null;
  traffit_exception_count?: number;
}

export interface CandidateContactOversightResponse {
  counters: CandidateContactOversightCounters;
  items: CandidateContactCase[];
  next_cursor?: string | null;
}

export interface CandidateContactAttemptInput {
  expected_version: number;
  outcome: CandidateContactOutcome;
  callback_at?: string | null;
  notes?: string | null;
  opportunity_outcomes: Array<{
    job_id: number;
    outcome: CandidateContactOpportunityOutcome;
  }>;
}

export interface CandidateContactReassignInput {
  expected_version: number;
  target_user_id?: number | null;
  reason: string;
}

export interface CandidateContactAttemptDraft {
  outcome: CandidateContactOutcome | null;
  callbackAt: string;
  notes: string;
  opportunityOutcomes: Record<number, CandidateContactOpportunityOutcome>;
}

export interface CandidateContactAttemptValidation {
  input: CandidateContactAttemptInput | null;
  errors: Record<string, string>;
}

export const candidateContactQueryKeys = {
  all: ["candidate-contact"] as const,
  status: () => ["candidate-contact", "status"] as const,
  queue: () => ["candidate-contact", "queue"] as const,
  candidate: (candidateId: number) =>
    ["candidate-contact", "candidate", candidateId] as const,
  oversight: () => ["candidate-contact", "oversight"] as const,
};

export const candidateContactApi = {
  status: () =>
    api
      .get<CandidateContactFeatureStatus>("/api/candidate-contact/status")
      .then((response) => response.data),
  queue: (params?: { cursor?: string; limit?: number }) =>
    api
      .get<CandidateContactQueueResponse>("/api/candidate-contact/queue", {
        params,
      })
      .then((response) => response.data),
  forCandidate: (candidateId: number) =>
    api
      .get<CandidateContactCase | null>(
        `/api/candidate-contact/candidates/${candidateId}`,
      )
      .then((response) => response.data),
  oversight: (params?: { cursor?: string; limit?: number }) =>
    api
      .get<CandidateContactOversightResponse>(
        "/api/candidate-contact/oversight",
        { params },
      )
      .then((response) => response.data),
  logAttempt: (
    caseId: number,
    input: CandidateContactAttemptInput,
    idempotencyKey: string,
  ) =>
    api
      .post<CandidateContactCase>(
        `/api/candidate-contact/cases/${caseId}/attempts`,
        input,
        { headers: { "Idempotency-Key": idempotencyKey } },
      )
      .then((response) => response.data),
  reassign: (caseId: number, input: CandidateContactReassignInput) =>
    api
      .post<CandidateContactCase>(
        `/api/candidate-contact/cases/${caseId}/reassign`,
        input,
      )
      .then((response) => response.data),
};

export function isCandidateContactVersionConflict(error: unknown): boolean {
  return error instanceof AxiosError && error.response?.status === 409;
}

export function candidateContactFullName(
  candidate: CandidateContactPerson,
): string {
  return (
    `${candidate.name ?? ""} ${candidate.lastname ?? ""}`.trim() || "Kandydat"
  );
}

export function buildCandidateContactAttemptInput(
  contactCase: CandidateContactCase,
  draft: CandidateContactAttemptDraft,
): CandidateContactAttemptValidation {
  const errors: Record<string, string> = {};
  if (!draft.outcome) errors.outcome = "Wybierz wynik próby.";

  const needsOpportunityResults =
    draft.outcome === "connected" ||
    draft.outcome === "callback_requested";
  if (needsOpportunityResults) {
    for (const opportunity of contactCase.opportunities) {
      if (!draft.opportunityOutcomes[opportunity.job_id]) {
        errors[`job-${opportunity.job_id}`] =
          "Wybierz wynik dla tej rekrutacji.";
      }
    }
  }

  const needsCallback =
    draft.outcome === "callback_requested" ||
    (needsOpportunityResults &&
      Object.values(draft.opportunityOutcomes).some(
        (value) => value === "maybe" || value === "not_presented",
      ));
  const parsedCallback = draft.callbackAt
    ? new Date(draft.callbackAt)
    : null;
  const callbackIso =
    parsedCallback && !Number.isNaN(parsedCallback.getTime())
      ? parsedCallback.toISOString()
      : null;
  if (needsCallback && !callbackIso) {
    errors.callback_at = "Wskaż prawidłowy termin oddzwonienia.";
  }

  if (!draft.outcome || Object.keys(errors).length > 0) {
    return { input: null, errors };
  }

  return {
    errors,
    input: {
      expected_version: contactCase.version,
      outcome: draft.outcome,
      callback_at: callbackIso,
      notes: draft.notes.trim() || null,
      opportunity_outcomes: needsOpportunityResults
        ? contactCase.opportunities.map((opportunity) => ({
            job_id: opportunity.job_id,
            outcome: draft.opportunityOutcomes[opportunity.job_id]!,
          }))
        : [],
    },
  };
}
