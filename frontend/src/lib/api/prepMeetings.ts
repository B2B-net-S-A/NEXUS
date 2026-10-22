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
  /** Notatka na Prep 2 z oceny Prepu 1 pary (22.10.2026); pusta = brak oceny. */
  prep1_followup?: PrepOptionsFollowup[];
}

export interface PrepOptionsFollowup {
  key: string;
  label: string;
  reason: PrepFollowupReason | null;
  note: string | null;
}

/**
 * Neutralne zdanie do zaproszenia na Prep 2 — tematy bez ocen („słaba
 * odpowiedź” zostaje w zespole). `null` = nic do dopisania.
 */
export function followupInvitationLine(items: Pick<PrepOptionsFollowup, "label">[]): string | null {
  const labels = items.map((i) => i.label.trim()).filter(Boolean);
  if (labels.length === 0) return null;
  const list =
    labels.length === 1 ? labels[0] : `${labels.slice(0, -1).join("; ")} oraz ${labels[labels.length - 1]}`;
  return `Na spotkaniu wrócimy do: ${list}.`;
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

export type PrepAnswerGrade = "strong" | "general" | "weak" | "missing" | "covered_in_prep1";
export type PrepFollowupReason = "weak" | "missing" | "missing_topic" | "general" | "unpracticed";

/** Ocena v2: temat prowadzącego z Ustawienia → Ocena prepów. */
export interface PrepTopicResult {
  key: string;
  label: string;
  required: boolean;
  status: "covered" | "partial" | "missing";
  quote: string | null;
  unverified?: boolean;
}

/** Ocena v2: odpowiedź kandydata (must-have, pytanie klienta, punkt z notatki). */
export interface PrepAnswer {
  key: string;
  label: string;
  kind: "must" | "question" | "followup";
  grade: PrepAnswerGrade;
  quote: string | null;
  note: string | null;
  unverified?: boolean;
}

/** Punkt „Do powtórzenia na Prep 2” z oceny Prepu 1. */
export interface PrepFollowupItem {
  key: string;
  label: string;
  kind: "must" | "question" | "topic";
  reason: PrepFollowupReason;
  quote: string | null;
  note: string | null;
}

/** Prep 2: punkt z notatki — przed (Prep 1) i po (Prep 2). */
export interface PrepComparisonRow {
  key: string;
  label: string;
  before: PrepFollowupReason | null;
  after: PrepAnswerGrade;
  quote: string | null;
}

export interface PrepReview {
  status: "ok" | "unavailable";
  level: "weak" | "ok" | "good" | null;
  coverage: number | null;
  criteria: {
    /** Kształt sprzed v2 — oceny sprzed 22.10.2026 mają tylko to. */
    items?: PrepReviewItem[];
    own_projects?: { told: boolean; quote: string | null };
    version?: number;
    topics?: PrepTopicResult[];
    answers?: PrepAnswer[];
    went_well?: string[];
    went_wrong?: string[];
    improve?: string[];
    scores?: Record<string, number | null>;
    weights_used?: Record<string, number>;
    total?: number | null;
    caps?: string[];
    followup?: PrepFollowupItem[];
    comparison?: PrepComparisonRow[];
  };
  summary: string | null;
  remaining: string[];
  /** Wersja Ustawienia → Ocena prepów (`null` = startowe). */
  config_version?: number | null;
  prompt_version?: string | null;
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

export interface PrepTranscriptCue {
  /** Sekunda od początku spotkania. */
  start: number;
  speaker: string | null;
  role: "staff" | "candidate" | "unknown" | null;
  text: string;
}

export interface PrepTranscript {
  event_id: number;
  speakers: PrepSpeaker[];
  text: string;
  fetched_at: string;
  /** Wypowiedzi z czasem i mówcą; pusta lista = stary zapis bez VTT. */
  cues?: PrepTranscriptCue[];
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
  /** Prowadzący ma wtedy zajęte, a planujący zapisuje mimo to (22.10.2026). */
  accept_busy?: boolean;
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
  /** Zajęte bloki prowadzącego od teraz do rozmowy — dla „Inna godzina…”. */
  busy?: { start: string; end: string }[];
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

/**
 * 409 `PREP_SLOT_BUSY`: prowadzący ma wtedy zajęte w kalendarzu (sprawdzone
 * przy zapisie, 22.10.2026). Okno pokazuje „Zapisz mimo to” (`accept_busy`).
 */
export function isPrepSlotBusy(error: unknown): boolean {
  const response = (error as { response?: { status?: number; data?: unknown } } | null)?.response;
  const detail = (response?.data as { detail?: { code?: unknown } } | null | undefined)?.detail;
  return response?.status === 409 && detail?.code === "PREP_SLOT_BUSY";
}

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

export const PREP_GRADE_LABELS: Record<PrepAnswerGrade, string> = {
  strong: "Mocna",
  general: "Ogólna",
  weak: "Słaba",
  missing: "Nie było",
  covered_in_prep1: "Mocna w Prep 1",
};

export const PREP_TOPIC_LABELS: Record<PrepTopicResult["status"], string> = {
  covered: "Omówione",
  partial: "Wspomniane",
  missing: "Nie było",
};

export const PREP_FOLLOWUP_REASON_LABELS: Record<PrepFollowupReason, string> = {
  weak: "Słaba odp.",
  missing: "Nie omówiono",
  missing_topic: "Temat pominięty",
  general: "Ogólna odp.",
  unpracticed: "Nieprzećwiczone",
};

export const PREP_CAP_LABELS: Record<string, string> = {
  too_short: "prep krótszy niż minimum z ustawień",
  required_topic_missing: "pominięty temat obowiązkowy",
  weak_must_answer: "słaba odpowiedź na must-have",
};

/** Ocena v2 (tematy, odpowiedzi, wnioski) — starsze mają tylko `items`. */
export function isReviewV2(review: PrepReview | null | undefined): boolean {
  return Boolean(review && review.status === "ok" && review.criteria.version === 2);
}

/** „01:02” albo „1:02:05” z sekund. */
export function formatCueTime(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${String(m).padStart(2, "0")}:${sec}`;
}

/** Normalizacja do szukania cytatu w wypowiedzi (spacje, wielkość liter). */
export function normalizeForQuote(text: string): string {
  return text.replace(/\s+/g, " ").trim().toLocaleLowerCase("pl");
}

/** Indeks pierwszej wypowiedzi, w której jest cytat; -1 = nie znaleziono. */
export function cueIndexForQuote(cues: PrepTranscriptCue[], quote: string | null): number {
  if (!quote) return -1;
  const full = normalizeForQuote(quote);
  // Cytat bywa dłuższy niż jedna wypowiedź z VTT — wtedy wystarczy jego początek.
  for (const length of [60, 25]) {
    const needle = full.slice(0, length);
    if (!needle) return -1;
    const index = cues.findIndex((cue) => normalizeForQuote(cue.text).includes(needle));
    if (index >= 0) return index;
  }
  return -1;
}

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
