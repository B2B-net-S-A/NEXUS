/**
 * Publiczny panel klienta pod linkiem z CV (`/k/{token}`) — lustro
 * `/api/public/panel/{token}`.
 *
 * Plik celowo nie importuje `@/lib/api`: tamta instancja axios dokleja token
 * zalogowanego użytkownika i przy 401 wyrzuca na logowanie, a klient z linku
 * nie ma konta. Ten sam wzorzec co `/cv/i/[token]` (goły axios). Pilnuje tego
 * test `client-panel-public-boundary`.
 *
 * Ekran dostaje `PanelTransport`, nie te funkcje wprost, bo harness
 * `/preview/client-panel` i testy podstawiają dane fikcyjne bez żadnego żądania.
 */
import axios from "axios";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://api.nexus.dynaminds.pl";

export type RequirementStatus = "project" | "list" | "none";

export type PanelCandidateState =
  | "none"
  | "question_open"
  | "answered"
  | "interview_requested"
  | "interview_confirmed"
  | "not_fit";

export type InterviewStatus =
  | "none"
  | "awaiting_recruiter"
  | "awaiting_dl"
  | "confirmed"
  | "cancelled";

export interface PanelRate {
  value: string;
  unit: "hourly" | "daily" | "monthly" | string;
  currency: string;
}

export interface PanelRequirement {
  key: string;
  label: string;
}

export interface PanelCandidate {
  public_id: string;
  name: string;
  title: string | null;
  city: string | null;
  available_from: string | null;
  available_label: string;
  available_confirmed_at: string | null;
  rate: PanelRate | null;
  statuses: Record<string, RequirementStatus>;
  in_projects: number;
  on_list: number;
  missing: number;
  sent_at: string | null;
  state: PanelCandidateState;
}

export interface PanelView {
  panel: {
    expires_at: string | null;
    show_rate: boolean;
    allow_actions: boolean;
    show_other_candidates: boolean;
  };
  job: {
    title: string;
    reference: string | null;
    client_name: string | null;
    request_text: string | null;
    added_at: string | null;
    work_mode: string | null;
    location: string | null;
    deadline: string | null;
  };
  owner: { name: string | null } | null;
  requirements: PanelRequirement[];
  candidates: PanelCandidate[];
}

export interface EvidenceItem {
  kind: "project" | "list";
  quote: string;
  term: string;
  where: string | null;
  dates: string | null;
}

export interface PanelFile {
  id: number;
  name: string;
  kind: string | null;
  url: string;
}

export interface PanelThreadItem {
  id: number;
  kind: string;
  author: string | null;
  at: string;
  body: string | null;
  answer: string | null;
  answered_at: string | null;
}

export interface PanelInterviewSlot {
  start: string;
  end: string | null;
  window_end: string | null;
}

export interface PanelCandidateDetail {
  public_id: string;
  name: string;
  cv: { available: boolean; filename: string | null; url: string | null };
  evidence: Record<string, { status: RequirementStatus; items: EvidenceItem[] }>;
  terms: {
    rate: PanelRate | null;
    available_label: string;
    available_confirmed_at: string | null;
    city: string | null;
  };
  files: PanelFile[];
  thread: PanelThreadItem[];
  interview: {
    status: InterviewStatus;
    slots: PanelInterviewSlot[];
    chosen: { start: string } | null;
  };
}

export interface PanelAuthor {
  author_name: string;
  author_email: string;
}

export interface PanelInterviewBody extends PanelAuthor {
  duration_minutes: number;
  slots: { start: string }[];
  interviewers?: string;
  prep_note?: string;
}

export interface PanelNotFitBody extends PanelAuthor {
  reasons: string[];
  body?: string;
}

export interface PanelQuestionBody extends PanelAuthor {
  body: string;
}

export type PanelEventAction = "open" | "candidate" | "requirement" | "tab" | "file";

export interface PanelEvent {
  public_id?: string;
  action: PanelEventAction;
  detail?: string;
}

/** Wszystko, czego ekran potrzebuje od serwera. */
export interface PanelTransport {
  fetchPanel: (publicId: string | null) => Promise<PanelView>;
  fetchCandidate: (publicId: string) => Promise<PanelCandidateDetail>;
  fetchCv: (url: string) => Promise<Blob>;
  /** Adres pod link „Pobierz”. */
  fileHref: (url: string) => string;
  sendQuestion: (publicId: string, body: PanelQuestionBody) => Promise<void>;
  sendInterview: (publicId: string, body: PanelInterviewBody) => Promise<void>;
  sendNotFit: (publicId: string, body: PanelNotFitBody) => Promise<void>;
  sendRequirementsChange: (body: PanelQuestionBody) => Promise<void>;
  /** Best-effort: nigdy nie odrzuca i niczego nie blokuje. */
  sendEvent: (event: PanelEvent) => void;
}

export function httpPanelTransport(token: string): PanelTransport {
  const base = `${API_BASE}/api/public/panel/${encodeURIComponent(token)}`;
  const candidate = (publicId: string) => `${base}/candidates/${encodeURIComponent(publicId)}`;
  return {
    fetchPanel: (publicId) =>
      axios
        .get<PanelView>(base, { params: publicId ? { c: publicId } : undefined })
        .then((r) => r.data),
    fetchCandidate: (publicId) =>
      axios.get<PanelCandidateDetail>(candidate(publicId)).then((r) => r.data),
    fetchCv: (url) =>
      axios.get<Blob>(`${API_BASE}${url}`, { responseType: "blob" }).then((r) => r.data),
    fileHref: (url) => `${API_BASE}${url}`,
    sendQuestion: (publicId, body) =>
      axios.post(`${candidate(publicId)}/questions`, body).then(() => undefined),
    sendInterview: (publicId, body) =>
      axios.post(`${candidate(publicId)}/interview`, body).then(() => undefined),
    sendNotFit: (publicId, body) =>
      axios.post(`${candidate(publicId)}/not-fit`, body).then(() => undefined),
    sendRequirementsChange: (body) =>
      axios.post(`${base}/requirements-change`, body).then(() => undefined),
    sendEvent: (event) => {
      void axios.post(`${base}/events`, event).catch(() => undefined);
    },
  };
}

export function panelKey(token: string, publicId: string | null) {
  return ["client-panel", token, publicId] as const;
}

export function panelCandidateKey(token: string, publicId: string) {
  return ["client-panel", token, "candidate", publicId] as const;
}

export function panelCvKey(token: string, publicId: string) {
  return ["client-panel", token, "cv", publicId] as const;
}
