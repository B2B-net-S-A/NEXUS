/**
 * Panel klienta od strony NEXUSA — lustro `/api/client-panel`. Osobny plik niż
 * `clientPanel.ts`, bo ten ciągnie `@/lib/api` (token użytkownika), którego
 * strona publiczna `/k/{token}` nie może mieć w paczce.
 */
import api from "@/lib/api";

export type ClientPanelRequestKind = "question" | "interview" | "not_fit" | "requirements_change";

export interface ClientPanelShareableDocument {
  id: number;
  name: string;
  kind: string;
}

export interface ClientPanelWeakEvidence {
  key: string;
  label: string;
  quote: string | null;
  where: string | null;
}

export interface ClientPanelPerson {
  candidate_id: number;
  name: string;
  public_id: string | null;
  hidden: boolean;
  in_projects: number;
  on_list: number;
  missing: number;
  weak: ClientPanelWeakEvidence[];
  /** Klucze wymagań, które DL już odrzucił (PATCH zastępuje całą listę). */
  rejected_evidence?: string[];
  shared_document_ids?: number[];
  documents?: ClientPanelShareableDocument[];
}

export interface ClientPanelSettings {
  job_closed: boolean;
  enabled: boolean;
  show_rate: boolean;
  show_other_candidates: boolean;
  allow_actions: boolean;
  expires_at: string | null;
  url: string | null;
  short_url: string | null;
  candidates: ClientPanelPerson[];
  views: { total: number; last_at: string | null; people: number };
  requests_open: number;
}

export type ClientPanelSettingsPatch = Partial<
  Pick<
    ClientPanelSettings,
    "enabled" | "show_rate" | "show_other_candidates" | "allow_actions" | "expires_at"
  >
>;

export interface ClientPanelRequestItem {
  id: number;
  kind: ClientPanelRequestKind;
  candidate_id: number | null;
  candidate_name: string | null;
  job_id: number;
  job_title: string | null;
  author_name: string | null;
  author_email: string | null;
  email_domain_known: boolean;
  body: string | null;
  reasons: string[] | null;
  slot_request_id: number | null;
  status: "open" | "answered" | "closed";
  answer: string | null;
  created_at: string;
}

export interface ClientPanelActivityItem {
  at: string;
  action: string;
  detail: string | null;
  candidate_name: string | null;
}

/** Wszystko, czego okno potrzebuje od serwera; harness podstawia dane fikcyjne. */
export interface ClientPanelAdminTransport {
  fetchSettings: (jobId: number) => Promise<ClientPanelSettings>;
  updateSettings: (jobId: number, patch: ClientPanelSettingsPatch) => Promise<void>;
  rotateLink: (jobId: number) => Promise<void>;
  updatePerson: (
    jobId: number,
    candidateId: number,
    patch: { hidden?: boolean; rejected_evidence?: string[]; shared_document_ids?: number[] },
  ) => Promise<void>;
  fetchRequests: (jobId: number) => Promise<ClientPanelRequestItem[]>;
  answerRequest: (id: number, body: { answer: string; send_email: boolean }) => Promise<void>;
  closeRequest: (id: number) => Promise<void>;
  fetchActivity: (jobId: number) => Promise<ClientPanelActivityItem[]>;
}

/** Odpowiedź listy bywa gołą tablicą albo `{items}`; ekran chce tablicę. */
function listOf<T>(data: T[] | { items: T[] }): T[] {
  return Array.isArray(data) ? data : data.items;
}

export const httpClientPanelAdminTransport: ClientPanelAdminTransport = {
  fetchSettings: (jobId) =>
    api.get<ClientPanelSettings>(`/api/client-panel/jobs/${jobId}`).then((r) => r.data),
  updateSettings: (jobId, patch) =>
    api.put(`/api/client-panel/jobs/${jobId}`, patch).then(() => undefined),
  rotateLink: (jobId) =>
    api.post(`/api/client-panel/jobs/${jobId}/rotate-link`).then(() => undefined),
  updatePerson: (jobId, candidateId, patch) =>
    api
      .patch(`/api/client-panel/jobs/${jobId}/candidates/${candidateId}`, patch)
      .then(() => undefined),
  fetchRequests: (jobId) =>
    api
      .get<ClientPanelRequestItem[] | { items: ClientPanelRequestItem[] }>(
        "/api/client-panel/requests",
        { params: { job_id: jobId, status: "open" } },
      )
      .then((r) => listOf(r.data)),
  answerRequest: (id, body) =>
    api.post(`/api/client-panel/requests/${id}/answer`, body).then(() => undefined),
  closeRequest: (id) => api.post(`/api/client-panel/requests/${id}/close`).then(() => undefined),
  fetchActivity: (jobId) =>
    api
      .get<ClientPanelActivityItem[] | { items: ClientPanelActivityItem[] }>(
        `/api/client-panel/jobs/${jobId}/activity`,
      )
      .then((r) => listOf(r.data)),
};

export function clientPanelAdminKey(jobId: number) {
  return ["client-panel-admin", jobId] as const;
}

export function clientPanelRequestsKey(jobId: number) {
  return ["client-panel-admin", jobId, "requests"] as const;
}

export function clientPanelActivityKey(jobId: number) {
  return ["client-panel-admin", jobId, "activity"] as const;
}
