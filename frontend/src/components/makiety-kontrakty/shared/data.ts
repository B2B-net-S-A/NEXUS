"use client";
// Dane makiet — odczyt na żywo ze stagingu tymi samymi trasami, z których
// korzysta dzisiejszy moduł. Klucze z prefiksem `mk-`, żeby nie mieszać
// pamięci podręcznej z prawdziwymi ekranami. Tylko GET.
import { useQueries, useQuery } from "@tanstack/react-query";
import api from "@/lib/api";

export interface MkRateStep {
  id: number;
  rate: number;
  effective_from: string | null;
  effective_to?: string | null;
  note?: string | null;
  source_order_id?: number | null;
  superseded?: boolean;
}

export interface MkContract {
  id: number;
  candidate_id: number | null;
  client_id: number;
  job_id: number | null;
  start_date: string | null;
  end_date: string | null;
  client_order_start_date: string | null;
  client_order_end_date: string | null;
  latest_order_end_date?: string | null;
  rate_candidate: number | null;
  rate_client: number | null;
  framework_rate: number | null;
  currency: string;
  /** Waluta stawki klienta i kandydata bywa różna (np. Bosch: klient w EUR, konsultant w PLN). */
  rate_client_currency?: string | null;
  rate_candidate_currency?: string | null;
  rate_unit: string;
  billing_hours_per_month: number | null;
  margin: number | null;
  candidate_rate_schedule?: MkRateStep[];
  client_rate_schedule?: MkRateStep[];
  framework_rate_schedule?: MkRateStep[];
  contract_type: string;
  status: string;
  work_mode: string | null;
  line_manager: string | null;
  client_pm_name: string | null;
  client_pm_contact_name?: string | null;
  team_name: string | null;
  project_name: string | null;
  termination_reason: string | null;
  termination_lessons: string | null;
  terminated_at: string | null;
  agreement_termination_mode: string | null;
  agreement_last_day: string | null;
  prolongation_status: string | null;
  missing_fields?: string[];
  candidate_name: string;
  client_name: string;
  job_title?: string | null;
  candidate_email_effective?: string | null;
  candidate_phone_effective?: string | null;
  monthly_rate_candidate?: number | null;
  monthly_rate_client?: number | null;
  monthly_margin?: number | null;
  can_reverse_termination?: boolean;
  created_at: string;
  updated_at: string;
}

export interface MkCareCard {
  contract_id: number;
  owner: { user_id: number; name: string; source: string } | null;
  cadence: { level: string; label: string } | null;
  health: { level: string; label: string; reasons: string[] } | null;
  kpis: {
    last_contact: unknown;
    satisfaction: unknown;
    manager_feedback: unknown;
    order_end: { on: string; days: number } | null;
  } | null;
  next_step: { kind: string; label: string; detail: string } | null;
  known_project: unknown;
  cases: unknown[];
  plan: { id: number; kind: string; label: string; due_on: string; status: string }[];
}

export interface MkActivity {
  id: number;
  action: string;
  details: Record<string, unknown> | null;
  user_id: number | null;
  user_name: string | null;
  created_at: string;
}

export interface MkDocument {
  id: number;
  contract_id: number;
  filename: string;
  /** contract | annex | order | other … */
  doc_type: string | null;
  content_type?: string | null;
  size_bytes: number | null;
  expiry_date: string | null;
  uploaded_by_email: string | null;
  created_at: string;
  /** „sharepoint_import”, „upload” … */
  source: string | null;
  folder_id: number | null;
  [key: string]: unknown;
}

export interface MkAmendment {
  id: number;
  contract_id: number;
  amendment_type: string;
  old_values: Record<string, unknown> | null;
  new_values: Record<string, unknown> | null;
  effective_date: string | null;
  reason: string | null;
  document_id: number | null;
  created_by_name: string | null;
  created_by_email: string | null;
  created_at: string;
  source: string | null;
  state: string | null;
  withdrawn: boolean;
  [key: string]: unknown;
}

// `status=active&status=ending` jak w liście kontraktów (bez `status[]`).
const get = <T,>(url: string, params?: Record<string, unknown>) =>
  api.get<T>(url, { params, paramsSerializer: { indexes: null } }).then((r) => r.data);

export function useMkContract(id: number) {
  return useQuery<MkContract>({
    queryKey: ["mk-contract", id],
    queryFn: () => get<MkContract>(`/api/contracts/${id}`),
    enabled: Number.isFinite(id),
  });
}

export function useMkCareCard(id: number) {
  return useQuery<MkCareCard>({
    queryKey: ["mk-care-card", id],
    queryFn: () => get<MkCareCard>(`/api/care/contracts/${id}/card`),
    enabled: Number.isFinite(id),
  });
}

export function useMkActivities(id: number) {
  return useQuery<MkActivity[]>({
    queryKey: ["mk-activities", id],
    queryFn: () => get<MkActivity[]>(`/api/contracts/${id}/activities`),
    enabled: Number.isFinite(id),
  });
}

export function useMkDocuments(id: number) {
  return useQuery<MkDocument[]>({
    queryKey: ["mk-documents", id],
    queryFn: () => get<MkDocument[]>(`/api/contracts/${id}/documents`),
    enabled: Number.isFinite(id),
  });
}

export function useMkAmendments(id: number) {
  return useQuery<MkAmendment[]>({
    queryKey: ["mk-amendments", id],
    queryFn: () => get<MkAmendment[]>(`/api/contracts/${id}/amendments`),
    enabled: Number.isFinite(id),
  });
}

export function useMkEquipment(id: number) {
  return useQuery<Record<string, unknown>[]>({
    queryKey: ["mk-equipment", id],
    queryFn: () => get<Record<string, unknown>[]>(`/api/contracts/${id}/equipment`),
    enabled: Number.isFinite(id),
  });
}

export function useMkInvoices(id: number) {
  return useQuery<Record<string, unknown>[]>({
    queryKey: ["mk-invoices", id],
    queryFn: () => get<Record<string, unknown>[]>(`/api/invoices`, { contract_id: id }),
    enabled: Number.isFinite(id),
  });
}

export function useMkNotes(id: number) {
  return useQuery<unknown>({
    queryKey: ["mk-notes", id],
    queryFn: () => get<unknown>(`/api/contracts/${id}/notes`),
    enabled: Number.isFinite(id),
  });
}

export function useMkRateHistory(id: number) {
  return useQuery<Record<string, unknown>[]>({
    queryKey: ["mk-rate-history", id],
    queryFn: () => get<Record<string, unknown>[]>(`/api/contracts/${id}/rate-history`),
    enabled: Number.isFinite(id),
  });
}

export function useMkBenchmark(id: number) {
  return useQuery<Record<string, unknown>>({
    queryKey: ["mk-benchmark", id],
    queryFn: () => get<Record<string, unknown>>(`/api/contracts/${id}/benchmark`),
    enabled: Number.isFinite(id),
    retry: false,
  });
}

export interface MkListItem extends MkContract {
  group_members?: unknown[];
}

export interface MkListResponse {
  items: MkListItem[];
  total: number;
  contractors_total?: number;
  contracts_total?: number;
  future_start_total?: number;
}

/** Jedna strona listy `/api/contracts` (serwer przyjmuje do 100 pozycji). */
export function useMkContractList(params: Record<string, unknown>, key: string) {
  return useQuery<MkListResponse>({
    queryKey: ["mk-contract-list", key],
    queryFn: () => get<MkListResponse>(`/api/contracts`, params),
  });
}

/** Cała lista (kilka stron po 100) — do grupowania po kliencie w makiecie. */
export function useMkContractListAll(params: Record<string, unknown>, pages: number) {
  const results = useQueries({
    queries: Array.from({ length: pages }, (_, i) => ({
      queryKey: ["mk-contract-list-all", JSON.stringify(params), i],
      queryFn: () => get<MkListResponse>(`/api/contracts`, { ...params, page: i + 1, page_size: 100 }),
    })),
  });
  const done = results.every((r) => r.isSuccess);
  const items = results.flatMap((r) => r.data?.items ?? []);
  return { done, items, total: results[0]?.data?.total ?? 0 };
}

/** Liczniki pigułek (jak `contracts-quick-counts`): ten sam zakres co lista. */
export function useMkQuickCounts() {
  const defs: { key: string; params: Record<string, unknown> }[] = [
    { key: "drafts", params: { status: ["draft", "ready_for_signature"] } },
    { key: "active", params: { status: ["active", "ending"] } },
    // „Wszystkie” = bez parametru statusu (serwer nie zna wartości `all`).
    { key: "ending", params: { bucket: "ending" } },
    { key: "all", params: {} },
  ];
  const results = useQueries({
    queries: defs.map((d) => ({
      queryKey: ["mk-quick-count", d.key],
      queryFn: () => get<MkListResponse>(`/api/contracts`, { ...d.params, page_size: 1 }),
    })),
  });
  return Object.fromEntries(defs.map((d, i) => [d.key, results[i]?.data?.total ?? null])) as Record<
    "drafts" | "active" | "ending" | "all",
    number | null
  >;
}
