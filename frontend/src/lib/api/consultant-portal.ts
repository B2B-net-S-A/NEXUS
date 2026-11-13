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
  rate: PortalRate | null;
  support_phone: string | null;
  menu: { start: boolean; equipment: boolean };
}

export interface PortalRate {
  amount: string;
  currency: string;
  unit: string;
}

export interface PortalTodoItem {
  key: string;
  title: string;
  detail: string;
  href: string;
}

export interface PortalMaterial {
  id: number;
  title: string;
  kind: "file" | "link";
  url: string | null;
  file_name: string | null;
  shared: boolean;
}

export interface PortalStart {
  start_date: string | null;
  first_day: {
    place: string | null;
    time: string | null;
    bring: string | null;
    contact_name: string | null;
  } | null;
  documents: { name: string; note: string | null; offset_days: number | null; required: boolean }[];
  materials: PortalMaterial[];
}

export interface PortalEquipmentItem {
  id: number;
  name: string;
  category: string;
  inventory_number: string | null;
  serial_number: string | null;
  since: string;
  protocol_id: number;
  protocol_number: string;
  protocol_status: string;
  protocol_label: string;
}

export interface PortalProtocol {
  id: number;
  number: string;
  kind: "wydanie" | "zwrot";
  date: string;
  status: string;
  label: string;
  items: string[];
  can_confirm: boolean;
}

export interface PortalEquipment {
  items: PortalEquipmentItem[];
  protocols: PortalProtocol[];
}

export type SettlementMode = "client_report" | "report_with_approval" | "own_report";

export interface PortalSettlement {
  mode: SettlementMode | null;
  instructions: string | null;
  buyer: { name: string; nip: string; address: string };
  payment_days: number;
}

export type TrainerForm = "online_or_onsite" | "online" | "onsite";

export interface PortalTrainerInput {
  topics: string[];
  experience: string;
  form: TrainerForm;
  day_rate: string;
  availability: string;
  materials: string;
}

export interface PortalTrainerApplication extends PortalTrainerInput {
  sent_at: string;
  waiting: { who: "nobody" | "us" | "other" | "done"; label: string };
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
  /** Trwa miesiąc z estymacją (`cl.estimate`): wysyłany plik to plan miesiąca. */
  plan?: boolean;
  documents: PortalDocument[];
  /** Rozliczenie klienta (E3); `null` przy wyłączonym module albo bez rozliczenia. */
  settlement?: PortalMonthSettlement | null;
  /** Dodatki do faktury w tym miesiącu; `null` przy wyłączonym module rozliczeń. */
  extras?: PortalExtra[] | null;
}

/** Dodatek do faktury (polecenie, weryfikacja, szkolenie, delegacja) ze stanem zgłoszenia. */
export interface PortalExtra {
  id: number;
  kind_label: string;
  description: string;
  amount: string;
  status: "pending" | "approved" | "rejected";
  status_label: string;
  /** Powód odrzucenia. */
  reason: string | null;
  documents: number;
}

/** Lista dozwolonych pól: bez stawki klienta, marży i mnożnika nadgodzin. */
export interface PortalMonthSettlement {
  status: "checking" | "ok" | "warnings" | "needs_fix" | "no_md" | "accepted";
  /** `estimate` — plan miesiąca (E5.3); bez danych do faktury. */
  kind?: "actual" | "estimate";
  label: string;
  fix_reason: string | null;
  checks: { state: "ok" | "warn" | "fail" | "none"; title: string }[];
  todo: string[];
  md_regular: string | null;
  md_extra: string | null;
  md_remaining_after: string | null;
  invoice: PortalSettlementInvoice | null;
}

/** Dane do faktury po przyjęciu RCP (E3.2) i faktura już w KSeF (E4). */
export interface PortalSettlementInvoice {
  amount_net: string | null;
  sale_date: string;
  payment_days: number;
  buyer?: { name: string; nip: string; address: string };
  item?: { description: string; quantity: string; net: string | null };
  /** Zatwierdzone dodatki: osobne pozycje faktury (kwota netto je zawiera). */
  extra_items?: { description: string; quantity: string; net: string }[];
  ksef?: {
    state: "in_ksef" | "differs" | "extra_pending";
    label: string;
    invoice_number: string | null;
    ksef_number: string;
    net_amount: string;
    due_date: string | null;
  } | null;
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
  financeOverview: () => getJson<{ months: PortalMonth[] }>("/finance/overview"),
  upload: async (form: FormData) =>
    (await (await request("/finance/documents", { method: "POST", body: form })).json()) as {
      id: number;
      duplicate: boolean;
    },
  /** Delegacja z dokumentami: dodatek „zgłoszony”, czeka na Finanse. */
  addTravel: async (form: FormData) =>
    (await (await request("/settlement/extras", { method: "POST", body: form })).json()) as {
      id: number;
      status: string;
    },
  downloadDocument: async (id: number): Promise<Blob> =>
    (await request(`/finance/documents/${id}/file`)).blob(),
  todo: () => getJson<{ items: PortalTodoItem[] }>("/todo"),
  start: () => getJson<PortalStart>("/start"),
  downloadMaterial: async (id: number): Promise<Blob> =>
    (await request(`/start/materials/${id}/file`)).blob(),
  settlement: () => getJson<PortalSettlement>("/settlement"),
  equipment: () => getJson<PortalEquipment>("/equipment"),
  downloadProtocol: async (id: number): Promise<Blob> =>
    (await request(`/equipment/protocols/${id}/document.pdf`)).blob(),
  confirmProtocol: (id: number, signerName: string) =>
    postJson<{ status: string }>(`/equipment/protocols/${id}/confirm`, {
      signer_name: signerName,
    }),
  trainer: () => getJson<{ application: PortalTrainerApplication | null }>("/trainer"),
  saveTrainer: async (body: PortalTrainerInput) =>
    (
      await request("/trainer", { method: "PUT", body: JSON.stringify(body) })
    ).json() as Promise<{ application: PortalTrainerApplication }>,
};

export const portalKeys = {
  me: ["consultant-portal", "me"] as const,
  faq: ["consultant-portal", "faq"] as const,
  cases: ["consultant-portal", "cases"] as const,
  meetings: ["consultant-portal", "meetings"] as const,
  hosts: (topic: PortalTopic) => ["consultant-portal", "hosts", topic] as const,
  finance: ["consultant-portal", "finance"] as const,
  todo: ["consultant-portal", "todo"] as const,
  start: ["consultant-portal", "start"] as const,
  settlement: ["consultant-portal", "settlement"] as const,
  equipment: ["consultant-portal", "equipment"] as const,
  trainer: ["consultant-portal", "trainer"] as const,
};

const retryExcept401 = (count: number, error: unknown): boolean =>
  !(error instanceof PortalApiError && error.status < 500) && count < 2;

export function usePortalQuery<T>(key: readonly unknown[], load: () => Promise<T>, enabled = true) {
  return useQuery({ queryKey: key, queryFn: load, enabled, retry: retryExcept401 });
}
