// Katalog raportów klienta (decyzje 15.11.2026): definicje per klient,
// kalendarz „co i komu w tym miesiącu”, pobranie i historia wysyłek.
// Backend: `backend/app/api/client_reports.py`.
import api from "@/lib/api";
import { fetchAuthenticatedDownload, downloadBlob } from "@/lib/authenticated-files";

export type ReportFamily = "settlement" | "management" | "compliance" | "on_request";
export type ReportRhythm =
  | "weekly"
  | "monthly"
  | "quarterly"
  | "semiannual"
  | "annual"
  | "contract_year"
  | "event"
  | "on_request";
export type ReportPreparer = "dl" | "finance" | "board" | "iod" | "consultant" | "client";
export type ReportState = "overdue" | "today" | "todo" | "sent" | "no_date";
export type DueRuleType =
  | "none"
  | "day_of_month"
  | "business_days_after"
  | "days_after"
  | "fixed"
  | "end_of_period";

export interface DueRule {
  type: DueRuleType;
  day?: number;
  days?: number;
  month?: number;
  anchor?: string;
}

export interface GeneratorParam {
  key: string;
  label: string;
  kind: "bool" | "text" | "number" | "tiers";
  default: unknown;
  hint: string | null;
}

export interface ReportGenerator {
  key: string;
  label: string;
  description: string;
  rhythms: ReportRhythm[];
  needs_amounts: boolean;
  needs_client_rate: boolean;
  params: GeneratorParam[];
}

export interface ReportNext {
  state: ReportState | null;
  due: string | null;
  period_key: string | null;
  period_label: string | null;
}

export interface ReportDefinition {
  id: number;
  client_id: number;
  name: string;
  family: ReportFamily;
  family_label: string;
  generator_key: string | null;
  generator_label: string | null;
  needs_amounts: boolean;
  params: Record<string, unknown>;
  rhythm: ReportRhythm;
  due_rule: DueRule;
  due_label: string;
  recipient: string | null;
  channel: string | null;
  file_format: string | null;
  preparer: ReportPreparer;
  preparer_user_id: number | null;
  preparer_label: string;
  source_kind: "contract" | "amendment" | "dl" | "manual";
  source_contract_id: number | null;
  source_chunk_id: number | null;
  source_ref: string | null;
  status: "proposal" | "active" | "rejected" | "archived";
  valid_from: string | null;
  valid_to: string | null;
  notes: string | null;
  confirmed_at: string | null;
  can_confirm: boolean;
  next: ReportNext;
  last_sent: { period_key: string; sent_at: string | null; sent_to: string | null } | null;
}

export interface ClientCatalog {
  client_id: number;
  can_edit: boolean;
  can_confirm: boolean;
  definitions: ReportDefinition[];
}

export type DefinitionInput = Pick<
  ReportDefinition,
  | "name"
  | "family"
  | "generator_key"
  | "params"
  | "rhythm"
  | "due_rule"
  | "recipient"
  | "channel"
  | "file_format"
  | "preparer"
  | "source_kind"
  | "source_ref"
  | "valid_from"
  | "valid_to"
  | "notes"
> & {
  preparer_user_id?: number | null;
  source_contract_id?: number | null;
  source_chunk_id?: number | null;
};

export interface ReportPeriod {
  key: string;
  label: string;
  start: string;
  end: string;
  due: string | null;
  state: ReportState;
  closed: boolean;
}

export interface ReportPreview {
  period_key: string;
  period_label: string;
  lines: { label: string; value: string; strong: boolean }[];
  checks: string[];
  sheets: { name: string; rows: number }[];
}

export interface ReportRun {
  id: number;
  period_key: string;
  status: "generated" | "sent";
  file_name: string | null;
  has_file: boolean;
  size_bytes: number | null;
  generated_by: string | null;
  sent_at: string | null;
  sent_to: string | null;
  sent_by: string | null;
  note: string | null;
  created_at: string | null;
}

export interface SuggestResult {
  created: ReportDefinition[];
  fragments: { chunk_id: number; contract_id: number; document: string; snippet: string }[];
  model_used: boolean;
  message: string | null;
}

export interface CalendarItem {
  due: string | null;
  carried: boolean;
  definition_id: number;
  client_id: number;
  client_name: string;
  report: string;
  family: ReportFamily;
  period_key: string;
  period_label: string;
  preparer_label: string;
  preparer_is_me: boolean;
  state: ReportState;
  has_generator: boolean;
}

export interface ReportsCalendar {
  month: string;
  today: string;
  items: CalendarItem[];
  upcoming: CalendarItem[];
  counts: Partial<Record<ReportState, number>>;
}

const BASE = "/api/client-reports";

export async function getGenerators(): Promise<ReportGenerator[]> {
  return (await api.get<ReportGenerator[]>(`${BASE}/generators`)).data;
}

export async function getClientCatalog(clientId: number): Promise<ClientCatalog> {
  return (await api.get<ClientCatalog>(`${BASE}/clients/${clientId}`)).data;
}

export async function createDefinition(clientId: number, body: DefinitionInput): Promise<ReportDefinition> {
  return (await api.post<ReportDefinition>(`${BASE}/clients/${clientId}/definitions`, body)).data;
}

export async function updateDefinition(id: number, body: DefinitionInput): Promise<ReportDefinition> {
  return (await api.patch<ReportDefinition>(`${BASE}/definitions/${id}`, body)).data;
}

export async function setDefinitionStatus(
  id: number,
  action: "confirm" | "reject" | "archive",
): Promise<ReportDefinition> {
  return (await api.post<ReportDefinition>(`${BASE}/definitions/${id}/${action}`)).data;
}

export async function suggestFromContracts(clientId: number): Promise<SuggestResult> {
  return (await api.post<SuggestResult>(`${BASE}/clients/${clientId}/suggest`)).data;
}

export async function getPeriods(id: number): Promise<ReportPeriod[]> {
  return (await api.get<ReportPeriod[]>(`${BASE}/definitions/${id}/periods`)).data;
}

export async function getPreview(id: number, period: string): Promise<ReportPreview> {
  return (await api.get<ReportPreview>(`${BASE}/definitions/${id}/preview`, { params: { period } })).data;
}

export async function getRuns(id: number): Promise<ReportRun[]> {
  return (await api.get<ReportRun[]>(`${BASE}/definitions/${id}/runs`)).data;
}

export async function downloadReport(id: number, period: string, fallbackName: string): Promise<void> {
  const file = await fetchAuthenticatedDownload(
    `${BASE}/definitions/${id}/export?period=${encodeURIComponent(period)}`,
  );
  downloadBlob(file.blob, file.filename ?? fallbackName);
}

export async function downloadRunFile(run: ReportRun): Promise<void> {
  const file = await fetchAuthenticatedDownload(`${BASE}/runs/${run.id}/file`);
  downloadBlob(file.blob, file.filename ?? run.file_name ?? "raport");
}

export interface MarkSentInput {
  period_key: string;
  sent_on: string;
  sent_to?: string;
  note?: string;
  run_id?: number;
  file?: File | null;
}

export async function markSent(id: number, input: MarkSentInput): Promise<ReportRun> {
  const form = new FormData();
  form.append("period_key", input.period_key);
  form.append("sent_on", input.sent_on);
  if (input.sent_to) form.append("sent_to", input.sent_to);
  if (input.note) form.append("note", input.note);
  if (input.run_id != null) form.append("run_id", String(input.run_id));
  if (input.file) form.append("file", input.file);
  return (await api.post<ReportRun>(`${BASE}/definitions/${id}/runs`, form)).data;
}

export async function getCalendar(month: string, mine: boolean): Promise<ReportsCalendar> {
  return (await api.get<ReportsCalendar>(`${BASE}/calendar`, { params: { month, mine } })).data;
}

export const STATE_LABELS: Record<ReportState, string> = {
  overdue: "Po terminie",
  today: "Dziś",
  todo: "Do przygotowania",
  sent: "Wysłany",
  no_date: "Termin do ustalenia",
};

export const RHYTHM_LABELS: Record<ReportRhythm, string> = {
  weekly: "co tydzień",
  monthly: "co miesiąc",
  quarterly: "co kwartał",
  semiannual: "co pół roku",
  annual: "co rok",
  contract_year: "co rok umowy",
  event: "zdarzeniowo",
  on_request: "na żądanie",
};

export const FAMILY_LABELS: Record<ReportFamily, string> = {
  settlement: "Rozliczenie miesiąca (dowód pracy do faktury)",
  management: "Raporty zarządcze z danych NEXUSA",
  compliance: "Zgodność i bezpieczeństwo",
  on_request: "Na żądanie klienta",
};

export const PREPARER_LABELS: Record<ReportPreparer, string> = {
  dl: "Delivery Lead",
  finance: "Finanse",
  board: "Zarząd",
  iod: "IOD",
  consultant: "konsultanci → Finanse",
  client: "przygotowuje klient",
};

export const CALENDAR_RHYTHMS: ReportRhythm[] = [
  "weekly",
  "monthly",
  "quarterly",
  "semiannual",
  "annual",
  "contract_year",
];

/** „2026-11-05” → „05.11”; inny rok niż `yearOf` dopisuje rok. */
export function shortDate(iso: string | null, yearOf?: string): string {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  const sameYear = yearOf ? yearOf.startsWith(y) : true;
  return sameYear ? `${d}.${m}` : `${d}.${m}.${y}`;
}
