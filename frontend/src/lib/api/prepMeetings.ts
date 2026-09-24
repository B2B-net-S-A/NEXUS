// Prepy w Teams (0364) — planowanie Prep 1/2, stan prepu, ocena i transkrypt.
//
// Lustro `backend/app/api/prep_meetings.py`. Klucze zapytań są funkcjami, żeby
// harness `/preview/calendar-cycle` zasiewał cache tymi samymi kluczami.

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export interface PrepPerson {
  id: number;
  name: string;
}

export interface PrepOptions {
  /** Integracja z Teams włączona i skonfigurowana (inaczej zwykłe zaproszenie). */
  enabled: boolean;
  auto_transcribe: boolean;
  /** Podpowiedź organizatora dla Prepu 1 i 2 (klucze "1" i "2"). */
  suggested: Record<string, PrepPerson | null>;
  team: PrepPerson[];
  /** Akapit o nagrywaniu dopisywany do zaproszenia. */
  notice: string;
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
  note?: string | null;
  client_request_id?: string | null;
}

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
  create: (body: PrepCreateInput) =>
    api.post<Prep>("/api/interview-cycle/preps", body).then((r) => r.data),
  get: (eventId: number) =>
    api.get<Prep>(`/api/interview-cycle/preps/${eventId}`).then((r) => r.data),
  transcript: (eventId: number) =>
    api
      .get<PrepTranscript>(`/api/interview-cycle/preps/${eventId}/transcript`)
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
