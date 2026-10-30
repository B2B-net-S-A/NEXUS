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
  PairDebriefInput,
  SlotRequest,
  SupersededOutlook,
} from "@/lib/interview-cycle";
import type { DebriefFromText } from "@/lib/debrief-from-text";
import type { SlotsFromMail } from "@/lib/interview-slot-mail";

/** Wynik potwierdzenia albo zmiany terminu: rozmowa w kalendarzu. */
export interface SlotConfirmResult {
  request: SlotRequest;
  event_id: number;
  outlook: string;
  cancelled_event_id?: number | null;
  /** Blokada przełożonej rozmowy w Outlooku rekrutera (runda 7). */
  superseded_outlook?: SupersededOutlook | null;
}

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
/** Archiwum rozmów (0383) wybrane po technologiach roli tej rekrutacji. */
export const clientQuestionArchiveQueryKey = (jobId: number) =>
  ["interview-cycle", "client-questions", "archive", jobId] as const;
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
    slots: { start: string; end?: string | null; window_end?: string | null }[];
    duration_minutes: number;
    respond_by?: string | null;
    note?: string | null;
    replaces_request_id?: number;
  }) => api.post<SlotRequest>("/api/interview-cycle/slots", body).then((r) => r.data),
  /** Terminy z wklejonego maila klienta — podpowiedź, niczego nie zapisuje. */
  readSlotsFromMail: (body: { text: string; mail_date?: string | null }) =>
    api
      .post<SlotsFromMail>("/api/interview-cycle/slots/from-mail", body)
      .then((r) => r.data),
  /** `start` — godzina rozmowy w oknie klienta (termin z `window_end`). */
  chooseSlot: (id: number, index: number, start?: string | null) =>
    api
      .post<SlotRequest>(`/api/interview-cycle/slots/${id}/choose`, start ? { index, start } : { index })
      .then((r) => r.data),
  /** „Po rozmowie” (PR 4): pytania i oferta z notatki z telefonu — niczego nie zapisuje. */
  debriefFromText: (text: string) =>
    api
      .post<DebriefFromText>("/api/interview-cycle/debrief/from-text", { text })
      .then((r) => r.data),
  /** „Wysłane klientowi” (0487). */
  clientReplied: (id: number) =>
    api.post<SlotRequest>(`/api/interview-cycle/slots/${id}/client-replied`).then((r) => r.data),
  /** „Klient wybrał inny termin” (0487): inny termin z tego wniosku. */
  changeSlot: (id: number, body: { index: number; start?: string | null }) =>
    api
      .post<SlotConfirmResult>(`/api/interview-cycle/slots/${id}/change`, body)
      .then((r) => r.data),
  confirmSlot: (
    id: number,
    body: { index?: number | null; add_to_outlook: boolean; supersedes_event_id?: number | null },
  ) =>
    api
      .post<SlotConfirmResult>(`/api/interview-cycle/slots/${id}/confirm`, body)
      .then((r) => r.data),
  /** Nieodbyte rozmowy pary, które potwierdzany termin może przełożyć. */
  replaceableInterviews: (id: number) =>
    api
      .get<{ id: number; start_time: string; end_time?: string | null }[]>(
        `/api/interview-cycle/slots/${id}/replaceable`,
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
  /** Pytania z rozmowy bez wskazania wydarzenia (20.10.2026). */
  savePairDebrief: (candidateId: number, jobId: number, body: PairDebriefInput) =>
    api
      .put<Debrief>(`/api/interview-cycle/pairs/${candidateId}/${jobId}/debrief`, body)
      .then((r) => r.data),
  /** Termin rozmowy u klienta z okna przesunięcia karty (20.10.2026). */
  createClientInterview: (body: {
    candidate_id: number;
    job_id: number;
    start: string;
    duration_minutes: number;
  }) =>
    api
      .post<{ event_id: number; start: string; end: string | null }>(
        "/api/interview-cycle/client-interviews",
        body,
      )
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
  clientQuestionArchive: (jobId: number, limit = 20) =>
    api
      .get<ArchiveQuestion[]>("/api/interview-cycle/client-questions/archive", {
        params: { job_id: jobId, limit },
      })
      .then((r) => r.data),
};

export interface ClientQuestion {
  id: number;
  text: string;
  created_at: string | null;
}

export interface ArchiveQuestion {
  id: number;
  text: string;
  /** Technologie tej rekrutacji, o które pyta pytanie. */
  matched: string[];
}

export function useInterviewCycle(
  scope: CycleScope,
  {
    enabled = true,
    // Okienko „Rozmowy” w pasku stoi na każdej stronie: odświeża je gniazdo,
    // a odpytywanie jest tylko siatką bezpieczeństwa (`lib/polling.ts`).
    refetchInterval = CYCLE_REFETCH_MS,
    staleTime = 30_000,
  }: { enabled?: boolean; refetchInterval?: number; staleTime?: number } = {},
) {
  return useQuery({
    queryKey: interviewCycleQueryKey(scope),
    queryFn: () => interviewCycleApi.overview(scope),
    enabled,
    refetchInterval,
    staleTime,
  });
}

/**
 * Archiwum pytań z rozmów tego klienta (Excel rekruterów sprzed NEXUSA),
 * tylko o technologie tej roli. Pobierane dopiero po rozwinięciu sekcji.
 */
export function useClientQuestionArchive(jobId: number | null, enabled: boolean) {
  return useQuery({
    queryKey: clientQuestionArchiveQueryKey(jobId ?? 0),
    queryFn: () => interviewCycleApi.clientQuestionArchive(jobId as number),
    enabled: enabled && jobId != null,
    staleTime: 5 * 60_000,
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
