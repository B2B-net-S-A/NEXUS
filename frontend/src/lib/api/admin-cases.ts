// „Ludzie w NEXUSIE” (16.10.2026) — Sprawy administracja@.
//
// Lustro `backend/app/api/admin_cases.py`. Zakres liczy serwer: obsługa
// skrzynki (uprawnienie „Sprawy”) widzi wszystkie sprawy, osoba przypisana bez
// uprawnienia — tylko swoje i może je komentować (`can_manage` / `can_comment`).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { CareHealth } from "@/lib/api/care-board";
import { HR_COUNTS_MUTATION_KEY } from "@/lib/api/hr";

export type CaseArea =
  | "onboarding"
  | "offboarding"
  | "negotiation"
  | "administration"
  | "marketing"
  | "other";
export type CasePriority = "P1" | "P2" | "P3";
export type CaseStatus = "new" | "in_progress" | "waiting" | "done" | "closed";
export type CaseSource = "manual" | "mail" | "contract" | "lifecycle" | "compass_import";

export interface CasePersonRef {
  id: number;
  name: string | null;
}

export interface CaseContractRef {
  id: number;
  candidate_name: string | null;
  client_name: string | null;
  start_date: string | null;
  end_date: string | null;
  /** Od 22.10.2026 (tablica z opieką): efektywny opiekun kontraktu. */
  care_owner_user_id?: number | null;
  care_owner_name?: string | null;
  candidate_id?: number | null;
  /** Zdrowie relacji — tylko dla czytającego z kręgu D11, inaczej `null`. */
  health?: CareHealth | null;
}

export interface CaseChecklistItem {
  text: string;
  done: boolean;
}

export interface CaseCard {
  id: number;
  title: string;
  area: CaseArea;
  priority: CasePriority;
  status: CaseStatus;
  due_on: string | null;
  follow_up_on: string | null;
  overdue: boolean;
  assignee: CasePersonRef | null;
  subject_user: CasePersonRef | null;
  contract: CaseContractRef | null;
  source: CaseSource;
  checklist_done: number;
  checklist_total: number;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
}

export interface CaseMessage {
  id: number;
  sender_email: string | null;
  sender_name: string | null;
  subject: string | null;
  received_at: string | null;
  body_text: string;
  attachments: {
    name: string;
    content_type: string | null;
    size: number | null;
    inline: boolean;
  }[];
}

export interface CaseComment {
  id: number;
  author: CasePersonRef | null;
  body: string;
  created_at: string;
}

/** Konsultant sprawy z kontraktem (sekcja „Konsultant” w panelu i pełnym widoku). */
export interface CaseConsultant {
  contract_id: number;
  candidate_id?: number | null;
  candidate_name: string | null;
  client_id?: number | null;
  client_name: string | null;
  role: string | null;
  form: string | null;
  order_end_on: string | null;
  /** Efektywny opiekun kontraktu — „Przypisz opiekunowi”. */
  owner_user_id?: number | null;
  owner_name: string | null;
  cadence_label: string | null;
  last_conversation: { on: string; excerpt: string | null } | null;
  other_open_cases: number;
  health: CareHealth | null;
}

/** Propozycja „Kogo dotyczy?” dla sprawy bez kontraktu (tylko obsługa Spraw) — nic nie wiąże się samo. */
export interface CaseLinkSuggestion {
  contract_id: number;
  candidate_name: string | null;
  client_name: string | null;
  reason: string | null;
}

export interface CaseDetail extends CaseCard {
  description: string | null;
  checklist: CaseChecklistItem[];
  lifecycle_case_id: number | null;
  created_by: CasePersonRef | null;
  messages: CaseMessage[];
  comments: CaseComment[];
  can_manage: boolean;
  can_comment: boolean;
  /** Od 22.10.2026: gdy sprawa ma kontrakt. */
  consultant?: CaseConsultant | null;
  /** Od 22.10.2026: gdy sprawa nie ma kontraktu. */
  link_suggestions?: CaseLinkSuggestion[];
}

/** Liczniki chipów: otwarte sprawy w zakresie i wyszukiwaniu, bez filtrów chipów. */
export interface CaseChipCounts {
  areas: Partial<Record<CaseArea, number>>;
  week: number;
  unassigned: number;
  /** „Moi podopieczni” — sprawy kontraktów, których opiekunem jest czytający. */
  mine_care?: number;
}

export interface CaseList {
  items: CaseCard[];
  total: number;
  truncated: boolean;
  done_this_month: number;
  /** Od 19.10.2026 (chipy tablicy); starsza odpowiedź ich nie ma. */
  counts?: CaseChipCounts;
  /** Dziś i piątek tego tygodnia w kalendarzu firmy (kolor terminu). */
  today?: string;
  week_end?: string;
  can_manage: boolean;
}

export interface CaseListFilters {
  mine?: boolean;
  area?: CaseArea | null;
  status?: CaseStatus | null;
  priority?: CasePriority | null;
  q?: string;
  include_closed?: boolean;
  /** „Na ten tydzień”: otwarte z terminem do piątku (też po terminie). */
  week?: boolean;
  /** „Bez osoby”: otwarte bez przypisanej osoby. */
  unassigned?: boolean;
  /** „Moi podopieczni”: sprawy kontraktów, których efektywnym opiekunem jest czytający. */
  mine_care?: boolean;
}

export interface CaseCreateInput {
  title: string;
  area: CaseArea;
  priority: CasePriority;
  due_on?: string | null;
  follow_up_on?: string | null;
  assignee_user_id?: number | null;
  description?: string | null;
  checklist?: CaseChecklistItem[];
  contract_id?: number | null;
  subject_user_id?: number | null;
}

export type CaseUpdateInput = Partial<CaseCreateInput> & {
  status?: CaseStatus;
  /** Wersja widziana przez edytującego; inna w bazie = 409. */
  expected_updated_at?: string;
};

export interface AssigneeOption {
  id: number;
  name: string;
  /** Ma uprawnienie „Sprawy” — obsługuje skrzynkę. */
  handler: boolean;
}

export const CASE_AREA_LABELS: Record<CaseArea, string> = {
  onboarding: "Onboarding",
  offboarding: "Offboarding",
  negotiation: "Negocjacje",
  administration: "Administracja",
  marketing: "Marketing",
  other: "Inne",
};

export const CASE_STATUS_LABELS: Record<CaseStatus, string> = {
  new: "Nowa",
  in_progress: "W toku",
  waiting: "Czeka na kogoś",
  done: "Zrobione",
  closed: "Zamknięta",
};

export const CASE_SOURCE_LABELS: Record<CaseSource, string> = {
  manual: "ręcznie",
  mail: "z maila",
  contract: "z kontraktu",
  lifecycle: "z odejścia",
  compass_import: "z Compassa",
};

export const CASE_AREAS = Object.keys(CASE_AREA_LABELS) as CaseArea[];
export const CASE_STATUSES = Object.keys(CASE_STATUS_LABELS) as CaseStatus[];

export const caseKeys = {
  all: ["admin-cases"] as const,
  list: (filters: CaseListFilters) => ["admin-cases", "list", filters] as const,
  detail: (id: number) => ["admin-cases", "detail", id] as const,
  assignees: ["admin-cases", "assignees"] as const,
  contracts: (q: string) => ["admin-cases", "contracts", q] as const,
};

function listParams(filters: CaseListFilters): Record<string, string> {
  const params: Record<string, string> = {};
  if (filters.mine) params.mine = "true";
  if (filters.area) params.area = filters.area;
  if (filters.status) params.status = filters.status;
  if (filters.priority) params.priority = filters.priority;
  if (filters.q?.trim()) params.q = filters.q.trim();
  if (filters.include_closed) params.include_closed = "true";
  if (filters.week) params.week = "true";
  if (filters.unassigned) params.unassigned = "true";
  if (filters.mine_care) params.mine_care = "true";
  return params;
}

export function useCases(filters: CaseListFilters, enabled = true) {
  return useQuery({
    queryKey: caseKeys.list(filters),
    queryFn: async () =>
      (await api.get<CaseList>("/api/cases", { params: listParams(filters) })).data,
    enabled,
  });
}

export function useCase(id: number) {
  return useQuery({
    queryKey: caseKeys.detail(id),
    queryFn: async () => (await api.get<CaseDetail>(`/api/cases/${id}`)).data,
    enabled: Number.isFinite(id) && id > 0,
  });
}

/**
 * Lista osób do spraw. `via: "care"` — dla zapisującego opiekę (okno rozmowy),
 * który nie musi mieć uprawnienia „Sprawy”.
 */
export function useCaseAssignees(enabled: boolean, via: "cases" | "care" = "cases") {
  return useQuery({
    queryKey: via === "care" ? [...caseKeys.assignees, "care"] : caseKeys.assignees,
    queryFn: async () =>
      (
        await api.get<{ items: AssigneeOption[] }>(
          via === "care" ? "/api/care/case-assignees" : "/api/cases/assignees",
        )
      ).data.items,
    enabled,
    staleTime: 5 * 60 * 1000,
  });
}

export function useCaseContractOptions(q: string, enabled: boolean) {
  const term = q.trim();
  return useQuery({
    queryKey: caseKeys.contracts(term),
    queryFn: async () =>
      (
        await api.get<{ items: CaseContractRef[] }>("/api/cases/contract-options", {
          params: { q: term },
        })
      ).data.items,
    enabled: enabled && term.length >= 2,
  });
}

function useInvalidateCases() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: caseKeys.all });
}

/** Nowa, zmieniona albo zamknięta sprawa zmienia licznik zakładki „Sprawy”. */
const CASE_COUNTS_MUTATION_KEY = [...HR_COUNTS_MUTATION_KEY, "case"] as const;

export function useCreateCase() {
  const invalidate = useInvalidateCases();
  return useMutation({
    mutationKey: CASE_COUNTS_MUTATION_KEY,
    mutationFn: async (payload: CaseCreateInput) =>
      (await api.post<CaseDetail>("/api/cases", payload)).data,
    onSuccess: invalidate,
  });
}

export function useUpdateCase(id: number) {
  const invalidate = useInvalidateCases();
  return useMutation({
    mutationKey: CASE_COUNTS_MUTATION_KEY,
    mutationFn: async (payload: CaseUpdateInput) =>
      (await api.patch<CaseDetail>(`/api/cases/${id}`, payload)).data,
    onSuccess: invalidate,
  });
}

/**
 * „Weź” na sprawie bez osoby — przypisanie do siebie zwykłą zmianą sprawy
 * z wersją karty: ktoś wziął ją w międzyczasie = 409, nie ciche nadpisanie.
 */
export function useTakeCase() {
  const invalidate = useInvalidateCases();
  return useMutation({
    mutationKey: CASE_COUNTS_MUTATION_KEY,
    mutationFn: async (input: { id: number; userId: number; expectedUpdatedAt: string }) =>
      (
        await api.patch<CaseDetail>(`/api/cases/${input.id}`, {
          assignee_user_id: input.userId,
          expected_updated_at: input.expectedUpdatedAt,
        })
      ).data,
    onSettled: invalidate,
  });
}

/**
 * Przesunięcie karty na tablicy (status) albo zmiana jednego pola z panelu —
 * zawsze z wersją karty: cudza zmiana w międzyczasie = 409, nie ciche
 * nadpisanie. Tablica odświeża się także po odmowie.
 */
export function usePatchCase() {
  const invalidate = useInvalidateCases();
  return useMutation({
    mutationKey: CASE_COUNTS_MUTATION_KEY,
    mutationFn: async (input: { id: number; patch: CaseUpdateInput }) =>
      (await api.patch<CaseDetail>(`/api/cases/${input.id}`, input.patch)).data,
    onSettled: invalidate,
  });
}

export function useCloseCase(id: number) {
  const invalidate = useInvalidateCases();
  return useMutation({
    mutationKey: CASE_COUNTS_MUTATION_KEY,
    mutationFn: async () => (await api.post<CaseDetail>(`/api/cases/${id}/close`)).data,
    onSuccess: invalidate,
  });
}

export function useAddCaseComment(id: number) {
  const invalidate = useInvalidateCases();
  return useMutation({
    mutationFn: async (body: string) =>
      (await api.post<CaseComment>(`/api/cases/${id}/comments`, { body })).data,
    onSuccess: invalidate,
  });
}
