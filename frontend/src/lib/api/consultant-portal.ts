// Portal konsultanta: lustro `backend/app/api/consultant_portal.py`.
//
// Celowo zwykły `fetch`, nigdy instancja axios z sesją pracownika: tamta dokleja JWT
// i przekierowuje na /login. Sesja portalu to osobny token w nagłówku
// `X-Portal-Session`, trzymany w `sessionStorage`, więc znika z zamknięciem karty.

import { useQuery } from "@tanstack/react-query";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const PREFIX = `${API_BASE}/api/public/consultant-portal`;
const SESSION_KEY = "nexus_consultant_portal_session";

export type PortalTopic = "invoice" | "contract" | "leave" | "access" | "next" | "data";

export interface PortalMe {
  first_name: string | null;
  client: string | null;
  since: string | null;
  until: string | null;
  support_email: string | null;
  topics: { key: PortalTopic; label: string }[];
}

export interface PortalFaqItem {
  id: number;
  topic: PortalTopic;
  question: string;
  answer: string;
  position: number;
}

export interface PortalCase {
  id: number;
  title: string;
  status: string;
  owner: string | null;
  waiting: { who: "nobody" | "us" | "other" | "done"; label: string };
  created_at: string;
  updated_at: string;
}

export interface PortalHost {
  id: number;
  name: string;
  team: string;
  matches_topic: boolean;
  calendar_available: boolean;
  slots: string[];
}

export interface PortalHosts {
  available: boolean;
  message: string | null;
  hosts: PortalHost[];
}

export interface PortalMeeting {
  id: number;
  topic: PortalTopic;
  topic_label: string;
  host: string | null;
  start_at: string;
  end_at: string;
  status: "booked" | "cancelled";
  join_url: string | null;
  can_cancel: boolean;
  can_rate: boolean;
}

export interface PortalFinanceStatus {
  available: boolean;
  message: string | null;
  verified: boolean;
  phone_hint: string | null;
}

export interface PortalDocument {
  id: number;
  kind: "report" | "invoice";
  status: "received" | "accepted" | "rejected" | "paid";
  file_name: string | null;
  channel: "portal" | "mailbox";
  created_at: string;
  reject_reason: string | null;
}

export interface PortalMonth {
  year: number;
  month: number;
  report_label: string;
  invoice_label: string;
  issue_invoice: boolean;
  action: "send_report" | "send_invoice" | null;
  documents: PortalDocument[];
}

export interface PortalRatingForm {
  host: string | null;
  start_at: string;
  topic_label: string;
}

export interface PortalRatingInput {
  score: number;
  resolved: boolean | null;
  comment: string | null;
}

/** Ten kształt czyta `apiErrorMessage`: `{ response: { status, data } }`. */
export class PortalApiError extends Error {
  response: { status: number; data: unknown };

  constructor(status: number, data: unknown) {
    super(`portal ${status}`);
    this.response = { status, data };
  }

  get status(): number {
    return this.response.status;
  }

  get code(): string | null {
    const detail = (this.response.data as { detail?: { code?: unknown } } | null)?.detail;
    return typeof detail?.code === "string" ? detail.code : null;
  }
}

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

export function portalSession(): string | null {
  return storage()?.getItem(SESSION_KEY) ?? null;
}

export function savePortalSession(token: string): void {
  storage()?.setItem(SESSION_KEY, token);
}

export function clearPortalSession(): void {
  storage()?.removeItem(SESSION_KEY);
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const session = portalSession();
  if (session) headers.set("X-Portal-Session", session);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(`${PREFIX}${path}`, { ...init, headers, cache: "no-store" });
  if (!response.ok) {
    let data: unknown;
    try {
      data = await response.json();
    } catch {
      data = undefined;
    }
    throw new PortalApiError(response.status, data);
  }
  return response;
}

async function getJson<T>(path: string): Promise<T> {
  return (await (await request(path)).json()) as T;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await request(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return (await response.json()) as T;
}

export const portalApi = {
  status: () => getJson<{ open: boolean }>("/status"),
  requestLink: (email: string) => postJson<{ message: string }>("/link", { email }),
  openSession: (token: string) =>
    postJson<{ session_token: string; expires_at: string }>("/session", { token }),
  logout: () => postJson<{ ok: boolean }>("/logout"),
  me: () => getJson<PortalMe>("/me"),
  faq: () => getJson<{ items: PortalFaqItem[] }>("/faq"),
  cases: () => getJson<{ items: PortalCase[] }>("/cases"),
  newCase: (body: { topic: PortalTopic; title: string; body: string }) =>
    postJson<{ id: number }>("/cases", body),
  hosts: (topic: PortalTopic) => getJson<PortalHosts>(`/booking/hosts?topic=${topic}`),
  meetings: () => getJson<{ items: PortalMeeting[]; note: string }>("/meetings"),
  book: (body: { host_user_id: number; start: string; topic: PortalTopic; reason: string }) =>
    postJson<{ id: number; join_url: string | null }>("/meetings", body),
  cancelMeeting: (id: number) => postJson<{ id: number }>(`/meetings/${id}/cancel`),
  rateMeeting: (id: number, body: PortalRatingInput) =>
    postJson<{ ok: boolean }>(`/meetings/${id}/rating`, body),
  ratingForm: (token: string) => postJson<PortalRatingForm>("/rating-form", { token }),
  rateByLink: (token: string, body: PortalRatingInput) =>
    postJson<{ ok: boolean }>("/rating", { token, ...body }),
  financeStatus: () => getJson<PortalFinanceStatus>("/finance/status"),
  sendCode: () => postJson<{ phone_hint: string | null }>("/finance/sms"),
  verifyCode: (code: string) => postJson<{ verified: boolean }>("/finance/verify", { code }),
  financeOverview: () => getJson<{ months: PortalMonth[] }>("/finance/overview"),
  upload: async (form: FormData) =>
    (await (await request("/finance/documents", { method: "POST", body: form })).json()) as {
      id: number;
      duplicate: boolean;
    },
  downloadDocument: async (id: number): Promise<Blob> =>
    (await request(`/finance/documents/${id}/file`)).blob(),
};

export const portalKeys = {
  me: ["consultant-portal", "me"] as const,
  faq: ["consultant-portal", "faq"] as const,
  cases: ["consultant-portal", "cases"] as const,
  meetings: ["consultant-portal", "meetings"] as const,
  hosts: (topic: PortalTopic) => ["consultant-portal", "hosts", topic] as const,
  financeStatus: ["consultant-portal", "finance-status"] as const,
  finance: ["consultant-portal", "finance"] as const,
};

const retryExcept401 = (count: number, error: unknown): boolean =>
  !(error instanceof PortalApiError && error.status < 500) && count < 2;

export function usePortalQuery<T>(key: readonly unknown[], load: () => Promise<T>, enabled = true) {
  return useQuery({ queryKey: key, queryFn: load, enabled, retry: retryExcept401 });
}
