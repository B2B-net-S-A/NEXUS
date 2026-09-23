// „Rozmowy u klienta” — API cyklu rozmowy kandydata u klienta.
//
// Typy w `lib/interview-cycle.ts` (lustro `backend/app/api/interview_cycle.py`).
// Klucze zapytań są funkcjami, żeby harness `/preview/calendar-cycle` zasiewał
// cache dokładnie tymi samymi kluczami co ekran.

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type {
  CycleOverview,
  CycleScope,
  Debrief,
  DebriefInput,
  SlotRequest,
} from "@/lib/interview-cycle";

/** Agenda odświeża się co minutę — odliczanie „zadzwoń teraz” musi żyć. */
export const CYCLE_REFETCH_MS = 60_000;

export const interviewCycleQueryKey = (scope: CycleScope) =>
  ["interview-cycle", scope] as const;
export const clientQuestionsQueryKey = (jobId: number) =>
  ["interview-cycle", "client-questions", jobId] as const;
/** Pula pytań klienta z debriefów — po rekrutacji albo (nowa rekrutacja) po kliencie. */
export const clientQuestionPoolQueryKey = (
  by: "job" | "client",
  id: number,
  limit: number,
) => ["interview-cycle", "client-questions", "pool", by, id, limit] as const;
export const debriefQueryKey = (eventId: number) =>
  ["interview-cycle", "debrief", eventId] as const;
export const interviewEventQueryKey = (eventId: number) =>
  ["interview-cycle", "event", eventId] as const;

/** Termin rozmowy u klienta (okno debriefu z bramki zna tylko id wydarzenia). */
export interface InterviewEventInfo {
  id: number;
  candidate_id: number;
  job_id: number | null;
  start: string;
  end: string | null;
  started: boolean;
}

export const interviewCycleApi = {
  overview: (scope: CycleScope) =>
    api
      .get<CycleOverview>("/api/interview-cycle", { params: { scope } })
      .then((r) => r.data),
  createSlots: (body: {
    candidate_id: number;
    job_id: number;
    slots: { start: string; end?: string | null }[];
    duration_minutes: number;
    respond_by?: string | null;
    note?: string | null;
  }) => api.post<SlotRequest>("/api/interview-cycle/slots", body).then((r) => r.data),
  chooseSlot: (id: number, index: number) =>
    api
      .post<SlotRequest>(`/api/interview-cycle/slots/${id}/choose`, { index })
      .then((r) => r.data),
  confirmSlot: (id: number, body: { index?: number | null; add_to_outlook: boolean }) =>
    api
      .post<{ request: SlotRequest; event_id: number; outlook: string }>(
        `/api/interview-cycle/slots/${id}/confirm`,
        body,
      )
      .then((r) => r.data),
  cancelSlots: (id: number) =>
    api.post<SlotRequest>(`/api/interview-cycle/slots/${id}/cancel`).then((r) => r.data),
  getEvent: (eventId: number) =>
    api
      .get<InterviewEventInfo>(`/api/interview-cycle/events/${eventId}`)
      .then((r) => r.data),
  getDebrief: (eventId: number) =>
    api
      .get<Debrief | null>(`/api/interview-cycle/events/${eventId}/debrief`)
      .then((r) => r.data),
  saveDebrief: (eventId: number, body: DebriefInput) =>
    api
      .put<Debrief>(`/api/interview-cycle/events/${eventId}/debrief`, body)
      .then((r) => r.data),
  clientQuestions: (jobId: number) =>
    api
      .get<ClientQuestion[]>("/api/interview-cycle/client-questions", {
        params: { job_id: jobId, limit: 10 },
      })
      .then((r) => r.data),
  clientQuestionPool: (by: "job" | "client", id: number, limit: number) =>
    api
      .get<ClientQuestion[]>("/api/interview-cycle/client-questions", {
        params: by === "job" ? { job_id: id, limit } : { client_id: id, limit },
      })
      .then((r) => r.data),
};

export interface ClientQuestion {
  id: number;
  text: string;
  created_at: string | null;
}

export function useInterviewCycle(
  scope: CycleScope,
  { enabled = true }: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: interviewCycleQueryKey(scope),
    queryFn: () => interviewCycleApi.overview(scope),
    enabled,
    refetchInterval: CYCLE_REFETCH_MS,
    staleTime: 30_000,
  });
}

export function useClientQuestions(jobId: number | null) {
  return useQuery({
    queryKey: clientQuestionsQueryKey(jobId ?? 0),
    queryFn: () => interviewCycleApi.clientQuestions(jobId as number),
    enabled: jobId != null,
    staleTime: 5 * 60_000,
  });
}

/**
 * Pytania, które klient zadawał kandydatom (debriefy po rozmowach u klienta).
 * Zasila panel w profilu Championa i podpowiedź na stronie nowej rekrutacji.
 */
export function useClientQuestionPool(
  by: "job" | "client",
  id: number | null,
  limit = 50,
) {
  return useQuery({
    queryKey: clientQuestionPoolQueryKey(by, id ?? 0, limit),
    queryFn: () => interviewCycleApi.clientQuestionPool(by, id as number, limit),
    enabled: id != null,
    staleTime: 5 * 60_000,
  });
}

export function useDebrief(eventId: number | null) {
  return useQuery({
    queryKey: debriefQueryKey(eventId ?? 0),
    queryFn: () => interviewCycleApi.getDebrief(eventId as number),
    enabled: eventId != null,
  });
}

export function useInterviewEvent(eventId: number | null) {
  return useQuery({
    queryKey: interviewEventQueryKey(eventId ?? 0),
    queryFn: () => interviewCycleApi.getEvent(eventId as number),
    enabled: eventId != null,
    staleTime: 60_000,
  });
}
