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

/** Zgłoszenie trenera (13.11.2026): bez formy i stawki za dzień, bo szkolenia są
 * wyłącznie zdalne (§ 3 umowy szkoleniowej), a cenę trener podaje w wycenie zamówienia. */
export interface PortalTrainerInput {
  topics: string[];
  experience: string;
  proposal_title: string;
  proposal_hours: string;
  audience: string;
  availability: string;
  materials: string;
}

export interface PortalTrainerApplication extends PortalTrainerInput {
  sample_name: string | null;
  sent_at: string;
  waiting: { who: "nobody" | "us" | "other" | "done"; label: string };
}

// ── Szkolenia: lustro `backend/app/services/trainings/core.py` ───────────────

export type TrainingStatus =
  | "draft"
  | "ordered"
  | "quoted"
  | "returned"
  | "accepted"
  | "trainer_signed"
  | "signed"
  | "cancelled";

export type DeliverableKey = "materials" | "presentation" | "audio" | "other";
export type FeeKey = "fee_prep" | "fee_delivery" | "fee_presentation" | "fee_audio" | "fee_rights";
export type HandoverState = "missing" | "submitted" | "accepted" | "returned";

export interface TrainingDeliverable {
  key: DeliverableKey;
  label: string;
  required: boolean;
  format: string;
  due_days: number | null;
}

export interface TrainingAgendaItem {
  title: string;
  minutes: number | null;
}

export interface TrainingFileRow {
  id: number;
  kind: "deliverable" | "recording" | "invoice" | "internal";
  deliverable_key: DeliverableKey | null;
  status: "submitted" | "accepted" | "returned" | "replaced";
  file_name: string;
  content_type: string | null;
  size_bytes: number | null;
  uploaded_at: string | null;
  review_note: string | null;
  reviewed_at: string | null;
  fix_due_on: string | null;
  for_participants: boolean;
}

export interface TrainingHandoverItem {
  key: DeliverableKey;
  label: string;
  format: string;
  due_days: number | null;
  required: boolean;
  state: HandoverState;
  files: TrainingFileRow[];
}

export interface TrainingFee {
  key: FeeKey;
  label: string;
  /** Element zamówienia, bez którego pozycja nie dotyczy (C: prezentacja, D: audio). */
  needs: DeliverableKey | null;
  amount: string | null;
}

/** Widok trenera: jego kwoty tak, uwagi wewnętrzne i zapisy uczestników nie. */
export interface PortalTraining {
  id: number;
  status: TrainingStatus;
  status_label: string;
  order: {
    title: string;
    topic: string;
    description: string;
    session_date: string | null;
    time_from: string;
    time_to: string;
    duration_minutes: number | null;
    platform: string;
    expected_participants: number | null;
    quote_due_on: string | null;
    participant_materials: string;
    deliverables: TrainingDeliverable[];
    knowledge_test: boolean;
    extra_terms: string;
  };
  quote: {
    agenda: TrainingAgendaItem[];
    own_materials: string;
    third_party_materials: string;
    quote_note: string;
    return_note: string | null;
    quoted_at: string | null;
  };
  fees: { items: TrainingFee[]; total: string | null };
  agreement: {
    number: string | null;
    generated_at: string | null;
    trainer_signed_at: string | null;
    company_signed_at: string | null;
  };
  payment: { invoice_ready_at: string | null; paid_at: string | null };
  handover: TrainingHandoverItem[];
  invoices: TrainingFileRow[];
  can_quote: boolean;
  can_sign: boolean;
  can_deliver: boolean;
  can_invoice: boolean;
  /** Link do spotkania Teams dla prowadzącego; jest dopiero po podpisie umowy. */
  join_url?: string | null;
  registrations?: number;
  recording_ready?: boolean;
  feedback?: { count: number; average: number | null; comments?: string[] };
}

export interface PortalTrainingRow {
  id: number;
  title: string;
  status: TrainingStatus;
  status_label: string;
  trainer_kind: "consultant" | "employee";
  trainer_name: string;
  session_date: string | null;
  total: string | null;
  invoice_ready_at: string | null;
  paid_at: string | null;
  published_at: string | null;
  can_publish: boolean;
}

export interface TrainingChapter {
  title: string;
  start_minute: number;
}

export interface LibraryFile {
  id: number;
  kind: "deliverable" | "recording" | "invoice" | "internal";
  file_name: string;
  content_type: string | null;
  size_bytes: number | null;
}

export interface LibraryRecording {
  id: number;
  title: string;
  topic: string;
  description: string;
  session_date: string | null;
  duration_minutes: number | null;
  trainer_kind: "consultant" | "employee";
  /** „registered” = nagranie tylko dla zapisanych (0696). */
  scope?: "library" | "registered";
  registered?: boolean;
  chapters: TrainingChapter[];
  files: LibraryFile[];
}

export interface LibraryLive {
  id: number;
  title: string;
  topic: string;
  session_date: string | null;
  time_from: string;
  time_to: string;
  platform: string;
  description?: string;
  seat_limit?: number | null;
  taken?: number;
  registered: boolean;
  leading?: boolean;
  join_url: string | null;
  /** Spotkanie założył NEXUS: zapis wysyła zaproszenie na adres z umowy. */
  invited?: boolean;
}

export interface PortalTranscriptSearch {
  available: boolean;
  hits: { second: number; text: string }[];
}

export interface PortalTrainings {
  mine: PortalTrainingRow[];
  library: { recordings: LibraryRecording[]; live: LibraryLive[] };
  applied: boolean;
}

export interface PortalQuoteInput {
  agenda: TrainingAgendaItem[];
  fee_prep: string | null;
  fee_delivery: string | null;
  fee_presentation: string | null;
  fee_audio: string | null;
  fee_rights: string | null;
  own_materials: string;
  third_party_materials: string;
  quote_note: string;
}

export type AgreementVersion = "draft" | "trainer" | "signed";

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
  ksef?: {
    state: "in_ksef" | "differs";
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
  if (init.body && !(init.body instanceof FormData) && !(init.body instanceof Blob))
    headers.set("Content-Type", "application/json");
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

function fileForm(file: File): FormData {
  const form = new FormData();
  form.set("file", file);
  return form;
}

/**
 * Duży plik (do 2 GB) jako surowe ciało z nazwą w nagłówku: serwer sprawdza sesję,
 * zanim przeczyta bajty (multipart był parsowany przed sesją).
 */
async function postRawFile(path: string, file: File): Promise<{ training: PortalTraining }> {
  const response = await request(path, {
    method: "POST",
    body: file,
    headers: {
      "Content-Type": file.type || "application/octet-stream",
      "X-File-Name": encodeURIComponent(file.name),
    },
  });
  return (await response.json()) as { training: PortalTraining };
}

async function postFile(path: string, file: File): Promise<{ training: PortalTraining }> {
  return (await (await request(path, { method: "POST", body: fileForm(file) })).json()) as {
    training: PortalTraining;
  };
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
  trainerSample: async (file: File) =>
    (await (await request("/trainer/sample", { method: "POST", body: fileForm(file) })).json()) as {
      application: PortalTrainerApplication;
    },
  trainings: () => getJson<PortalTrainings>("/trainings"),
  training: (id: number) => getJson<{ training: PortalTraining }>(`/trainings/${id}`),
  saveQuote: async (id: number, body: PortalQuoteInput) =>
    (
      await request(`/trainings/${id}/quote`, { method: "PUT", body: JSON.stringify(body) })
    ).json() as Promise<{ training: PortalTraining }>,
  agreementPdf: async (id: number, version: AgreementVersion): Promise<Blob> =>
    (await request(`/trainings/${id}/agreement.pdf?version=${version}`)).blob(),
  uploadSignature: (id: number, file: File) => postFile(`/trainings/${id}/agreement/signature`, file),
  uploadDeliverable: (id: number, key: DeliverableKey, file: File) =>
    postRawFile(`/trainings/${id}/deliverables/${key}`, file),
  uploadInvoice: (id: number, file: File) => postFile(`/trainings/${id}/invoice`, file),
  trainingFile: async (fileId: number): Promise<Blob> =>
    (await request(`/trainings/files/${fileId}?download=true`)).blob(),
  /** Adres pliku dla `<video>`/`<audio>`: odtwarzacz nie wyśle nagłówka sesji, więc bilet. */
  fileTicket: async (fileId: number) => {
    const { url } = await getJson<{ url: string }>(`/trainings/files/${fileId}/ticket`);
    return { url: url.startsWith("/") ? `${API_BASE}${url}` : url };
  },
  register: (id: number, join: boolean) =>
    postJson<{ registered: boolean }>(`/trainings/${id}/registration`, { join }),
  rate: (id: number, rating: number) =>
    postJson<{ rating: number }>(`/trainings/${id}/feedback`, { rating, comment: "" }),
  transcript: (id: number, q: string) =>
    getJson<PortalTranscriptSearch>(`/trainings/${id}/transcript?q=${encodeURIComponent(q)}`),
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
  trainings: ["consultant-portal", "trainings"] as const,
  training: (id: number) => ["consultant-portal", "training", id] as const,
  ticket: (fileId: number) => ["consultant-portal", "ticket", fileId] as const,
};

const retryExcept401 = (count: number, error: unknown): boolean =>
  !(error instanceof PortalApiError && error.status < 500) && count < 2;

export function usePortalQuery<T>(key: readonly unknown[], load: () => Promise<T>, enabled = true) {
  return useQuery({ queryKey: key, queryFn: load, enabled, retry: retryExcept401 });
}
