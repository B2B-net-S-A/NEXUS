// Follow-up z kandydatem, gdy klient milczy (0371, decyzje Artura 24.09.2026).
//
// Typy są lustrem `backend/app/api/candidate_followups.py`. Kto dzwoni i kiedy
// liczy SERWER (`services/candidate_followups.py`) — front tylko pokazuje
// i zapisuje wynik telefonu.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import api from "@/lib/api";
import { BOARD_TASKS_QUERY_KEY } from "@/lib/api/boardTasks";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";

export type FollowupState = "overdue" | "today" | "tomorrow" | "scheduled";
export type FollowupColumn = "cv_sent" | "client_interview";
export type FollowupCallerReason =
  | "furthest"
  | "recent_contact"
  | "substitute"
  | "next_process"
  | "claim"
  | "none";
export type FollowupOutcome = "connected" | "changed" | "no_answer" | "callback";
export type FollowupProcessFlag = "interested" | "withdrawing";

export interface FollowupProcess {
  job_id: number;
  job_title: string;
  client_name: string | null;
  column: FollowupColumn;
  stage_name: string | null;
  sent_at: string;
  silent_since: string;
  silent_days: number;
  owner_id: number | null;
  owner_name: string | null;
  /** Ostatnia notatka w tym procesie — tylko w szczegółach kandydata. */
  last_note?: string | null;
  last_note_by?: string | null;
  last_note_at?: string | null;
}

export interface FollowupRow {
  candidate_id: number;
  candidate_name: string;
  phone: string | null;
  /** Dzień telefonu (RRRR-MM-DD, kalendarz firmy). */
  due_on: string;
  state: FollowupState;
  overdue_days: number;
  caller_id: number | null;
  caller_name: string | null;
  caller_reason: FollowupCallerReason | string;
  /** Pierwszy = proces, który zaszedł najdalej. */
  processes: FollowupProcess[];
  last_contact_at: string | null;
  last_contact_by: string | null;
  last_contact_kind: string | null;
  no_answer_count: number;
  pending: "no_answer" | "callback" | null;
}

export interface FollowupHistoryRow {
  outcome: FollowupOutcome | "claim";
  user_name: string | null;
  created_at: string;
  callback_on: string | null;
  note: string | null;
}

export interface FollowupDetail {
  candidate_id: number;
  /** `null` = kandydat nie czeka na odpowiedź klienta. */
  followup: FollowupRow | null;
  history: FollowupHistoryRow[];
}

/** Plakietka follow-upu na karcie Tablicy (`followup` w payloadzie kanbana). */
export interface FollowupCardBadge {
  caller_id: number | null;
  caller_name: string | null;
  due_on: string;
  state: FollowupState;
  overdue_days: number;
  process_count: number;
}

export interface FollowupOutcomeInput {
  outcome: FollowupOutcome;
  note?: string | null;
  callback_on?: string | null;
  processes?: Record<number, FollowupProcessFlag>;
}

export const candidateFollowupKeys = {
  detail: (candidateId: number) => ["candidate-followup", candidateId] as const,
};

export function useCandidateFollowup(candidateId: number | null, enabled = true) {
  return useQuery<FollowupDetail>({
    queryKey: candidateFollowupKeys.detail(candidateId ?? 0),
    queryFn: () =>
      api
        .get<FollowupDetail>(`/api/candidate-followups/candidates/${candidateId}`)
        .then((r) => r.data),
    enabled: enabled && candidateId != null,
    staleTime: 30_000,
  });
}

function useInvalidateFollowup() {
  const queryClient = useQueryClient();
  return (candidateId: number, data?: FollowupDetail) => {
    if (data) queryClient.setQueryData(candidateFollowupKeys.detail(candidateId), data);
    void queryClient.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
    // Oba kształty klucza tablicy (`["kanban", "12"]` i `["kanban", 12]`).
    void queryClient.invalidateQueries({ queryKey: ["kanban"] });
    void queryClient.invalidateQueries({ queryKey: candidateQueryKeys.notes(candidateId) });
    void queryClient.invalidateQueries({ queryKey: candidateQueryKeys.timelineRoot(candidateId) });
  };
}

export function useRecordFollowupOutcome(candidateId: number) {
  const invalidate = useInvalidateFollowup();
  return useMutation({
    mutationFn: (input: FollowupOutcomeInput) =>
      api
        .post<FollowupDetail>(
          `/api/candidate-followups/candidates/${candidateId}/outcome`,
          input,
        )
        .then((r) => r.data),
    onSuccess: (data) => invalidate(candidateId, data),
  });
}

export function useClaimFollowup(candidateId: number) {
  const invalidate = useInvalidateFollowup();
  return useMutation({
    mutationFn: () =>
      api
        .post<FollowupDetail>(`/api/candidate-followups/candidates/${candidateId}/claim`)
        .then((r) => r.data),
    onSuccess: (data) => invalidate(candidateId, data),
  });
}
