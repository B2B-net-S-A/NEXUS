// Prepy w Teams (0370) — planowanie Prep 1/2, stan prepu, ocena i transkrypt.
//
// Lustro `backend/app/api/prep_meetings.py`. Klucze zapytań są funkcjami, żeby
// harness `/preview/calendar-cycle` zasiewał cache tymi samymi kluczami.

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { Prep2Skip, Prep2SkipReason } from "@/lib/interview-cycle";
import type { PrepInvitation } from "@/lib/prep-invitation";

export interface PrepPerson {
  id: number;
  name: string;
}

/** Osoba do zaproszenia — każdy aktywny w NEXUSIE (17.10.2026, D1). */
export interface PrepPersonOption extends PrepPerson {
  /** Rola główna (`UserRole`); etykietę daje `ROLE_LABELS`. */
  role: string | null;
  /** W zespole tej rekrutacji — na górze listy. */
  in_team: boolean;
}

/** Zaproszony na prep (bez kandydata). `user_id` puste = spoza NEXUSA. */
export interface PrepAttendee {
  email: string;
  user_id: number | null;
  name: string | null;
}

export interface PrepOptions {
  /** Integracja z Teams włączona i skonfigurowana (inaczej zwykłe zaproszenie). */
  enabled: boolean;
  auto_transcribe: boolean;
  /** Podpowiedź organizatora dla Prepu 1 i 2 (klucze "1" i "2"). */
  suggested: Record<string, PrepPerson | null>;
  team: PrepPerson[];
  /** Wszyscy, których można zaprosić; starszy serwer = brak (wtedy `team`). */
  people?: PrepPersonOption[];
  /** Adnotacja o nagrywaniu pod treścią zaproszenia. */
  notice: string;
  /** Zaproszenie dla kandydata (klucze "1" i "2"); starszy serwer = brak. */
  invitation?: Record<string, PrepInvitation>;
}

export type PrepItemStatus = "covered" | "partial" | "missing" | "covered_in_prep1";

export interface PrepReviewItem {
  key: string;
  label: string;
  kind: "must" | "question";
  status: PrepItemStatus;
  quote: string | null;
  unverified?: boolean;
}

export interface PrepReview {
  status: "ok" | "unavailable";
  level: "weak" | "ok" | "good" | null;
  coverage: number | null;
  criteria: {
    items?: PrepReviewItem[];
    own_projects?: { told: boolean; quote: string | null };
  };
  summary: string | null;
  remaining: string[];
}

export type TranscriptStatus =
  | "waiting"
  | "fetched"
  | "missing"
  | "cancelled"
  | "forbidden"
  | "error";

export interface Prep {
  event_id: number;
  prep_no: 1 | 2;
  candidate_id: number;
  job_id: number;
  organizer: PrepPerson | null;
  /** Kto założył prep — też może go zmienić. */
  scheduled_by?: PrepPerson | null;
  attendees?: PrepAttendee[];
  status?: "scheduled" | "completed" | "cancelled";
  /** Zmienić i odwołać mogą ludzie pary (prowadzący, DL, rekruter, planujący), HoR i admin. */
  can_edit?: boolean;
  /** Odpowiedź kandydata z Outlooka prowadzącego (0453); `null` = nie sprawdzano. */
  candidate_response?: "none" | "accepted" | "tentative" | "declined" | null;
  candidate_response_at?: string | null;
  /** Termin zaproponowany przez kandydata. */
  proposed_start?: string | null;
  proposed_end?: string | null;
  start: string;
  end: string | null;
  online_meeting_url: string | null;
  transcription_setup: "pending" | "enabled" | "failed" | "disabled";
  transcript_status: TranscriptStatus;
  talk_share: number | null;
  duration_seconds: number | null;
  review: PrepReview | null;
}

export interface PrepSpeaker {
  name: string;
  role: "candidate" | "staff" | "unknown";
  user_id: number | null;
  seconds: number;
}

export interface PrepTranscript {
  event_id: number;
  speakers: PrepSpeaker[];
  text: string;
  fetched_at: string;
}

export interface PrepCreateInput {
  candidate_id: number;
  job_id: number;
  prep_no: 1 | 2;
  organizer_user_id: number;
  start: string;
  end: string;
  attendee_user_ids: number[];
  attendee_emails?: string[];
  note?: string | null;
  client_request_id?: string | null;
}

/** Zmiana prepu. Brak pola = bez zmian; `attendee_*` podane = pełna nowa lista. */
export interface PrepUpdateInput {
  start?: string;
  end?: string;
  organizer_user_id?: number;
  attendee_user_ids?: number[];
  attendee_emails?: string[];
  client_request_id?: string | null;
}

/** Wolne godziny prepu z kalendarza prowadzącego (20.10.2026, PR 2). */
export interface PrepSuggestion {
  prep_no: 1 | 2;
  organizer: PrepPerson | null;
  /** ok — z kalendarza; unavailable — NEXUS go nie widzi; off — prepy w Teams wyłączone. */
  calendar: "ok" | "unavailable" | "off";
  /** Prep tej rundy już jest — bez podpowiedzi. */
  scheduled_start: string | null;
  minutes: number;
  options: { start: string; end: string }[];
}

export interface PrepSuggestions {
  enabled: boolean;
  preps: PrepSuggestion[];
}

export interface PrepSuggestionsParams {
  candidateId: number;
  jobId: number;
  interviewStart: string;
  candidateFrom?: string | null;
  candidateTo?: string | null;
}

export const prepSuggestionsQueryKey = (p: PrepSuggestionsParams) =>
  [
    "interview-cycle",
    "preps",
    "suggestions",
    p.candidateId,
    p.jobId,
    p.interviewStart,
    p.candidateFrom ?? "",
    p.candidateTo ?? "",
  ] as const;

export const prepOptionsQueryKey = (candidateId: number, jobId: number) =>
  ["interview-cycle", "preps", "options", candidateId, jobId] as const;
export const prepQueryKey = (eventId: number) =>
  ["interview-cycle", "preps", eventId] as const;
export const prepTranscriptQueryKey = (eventId: number) =>
  ["interview-cycle", "preps", eventId, "transcript"] as const;

export const prepMeetingsApi = {
  options: (candidateId: number, jobId: number) =>
    api
      .get<PrepOptions>("/api/interview-cycle/preps/options", {
        params: { candidate_id: candidateId, job_id: jobId },
      })
      .then((r) => r.data),
  suggestions: (p: PrepSuggestionsParams) =>
    api
      .get<PrepSuggestions>("/api/interview-cycle/preps/suggestions", {
        params: {
          candidate_id: p.candidateId,
          job_id: p.jobId,
          interview_start: p.interviewStart,
          ...(p.candidateFrom ? { candidate_from: p.candidateFrom } : {}),
          ...(p.candidateTo ? { candidate_to: p.candidateTo } : {}),
        },
      })
      .then((r) => r.data),
  create: (body: PrepCreateInput) =>
    api.post<Prep>("/api/interview-cycle/preps", body).then((r) => r.data),
  get: (eventId: number) =>
    api.get<Prep>(`/api/interview-cycle/preps/${eventId}`).then((r) => r.data),
  update: (eventId: number, body: PrepUpdateInput) =>
    api.patch<Prep>(`/api/interview-cycle/preps/${eventId}`, body).then((r) => r.data),
  cancel: (eventId: number, comment: string | null) =>
    api
      .post<Prep>(`/api/interview-cycle/preps/${eventId}/cancel`, { comment })
      .then((r) => r.data),
  transcript: (eventId: number) =>
    api
      .get<PrepTranscript>(`/api/interview-cycle/preps/${eventId}/transcript`)
      .then((r) => r.data),
};

/** Rozmowa bez Prepu 2 (0482): powód i telefon do kandydata przed rozmową. */
export interface Prep2SkipCreateInput {
  candidate_id: number;
  job_id: number;
  reason: Prep2SkipReason;
  reason_note: string | null;
  /** ISO — kiedy rekruter zadzwoni do kandydata (przed rozmową). */
  call_at: string;
}

export const prep2SkipApi = {
  create: (body: Prep2SkipCreateInput) =>
    api.post<Prep2Skip>("/api/interview-cycle/prep2-skip", body).then((r) => r.data),
  callDone: (skipId: number, note: string | null) =>
    api
      .post<Prep2Skip>(`/api/interview-cycle/prep2-skip/${skipId}/call-done`, { note })
      .then((r) => r.data),
};

export function usePrepOptions(candidateId: number | null, jobId: number | null) {
  return useQuery({
    queryKey: prepOptionsQueryKey(candidateId ?? 0, jobId ?? 0),
    queryFn: () => prepMeetingsApi.options(candidateId as number, jobId as number),
    enabled: candidateId != null && jobId != null,
    staleTime: 60_000,
  });
}

export function usePrep(eventId: number | null) {
  return useQuery({
    queryKey: prepQueryKey(eventId ?? 0),
    queryFn: () => prepMeetingsApi.get(eventId as number),
    enabled: eventId != null,
    staleTime: 30_000,
  });
}

export function usePrepTranscript(eventId: number | null, enabled: boolean) {
  return useQuery({
    queryKey: prepTranscriptQueryKey(eventId ?? 0),
    queryFn: () => prepMeetingsApi.transcript(eventId as number),
    enabled: enabled && eventId != null,
    staleTime: 5 * 60_000,
  });
}

// ── Prezentacja ────────────────────────────────────────────────────────────────

export const PREP_LEVEL_LABELS: Record<"weak" | "ok" | "good", string> = {
  weak: "Słaby",
  ok: "OK",
  good: "Dobry",
};

export const PREP_ITEM_LABELS: Record<PrepItemStatus, string> = {
  covered: "Omówione",
  partial: "Wspomniane",
  missing: "Nie było",
  covered_in_prep1: "Omówione w Prep 1",
};

/** Stan prepu po spotkaniu jednym zdaniem — nigdy pustka zamiast awarii. */
export function prepStatusLine(prep: Prep): string {
  switch (prep.transcript_status) {
    case "waiting":
    case "error":
      return "Czekamy na transkrypt z Teams — pojawi się kilkanaście minut po spotkaniu.";
    case "forbidden":
      return "NEXUS nie ma dostępu do tego spotkania w Teams — poproś administratora o sprawdzenie konfiguracji.";
    case "missing":
      return "Z tego prepu nie ma transkryptu — spotkanie nie było nagrywane albo się nie odbyło.";
    case "cancelled":
      return "Prep został odwołany.";
    case "fetched":
      if (!prep.review) return "Transkrypt jest, ocena jeszcze się liczy.";
      return prep.review.status === "ok"
        ? ""
        : "Ocena AI jest niedostępna — przeczytaj transkrypt.";
  }
}

export function formatTalkShare(share: number | null): string {
  return share == null ? "nie policzono" : `${Math.round(share * 100)}%`;
}
