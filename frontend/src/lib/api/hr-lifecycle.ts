// „Ludzie w NEXUSIE” (16.10.2026) — wejście i odejście.
//
// Lustro `backend/app/api/hr_lifecycle.py`. Kto co widzi (Kadry, przełożony,
// wykonawca zadania), terminy w dniach roboczych, przekazanie pracy o 18:00
// ostatniego dnia i wyłączenie konta dzień później liczy serwer; front pokazuje
// to, co dostał. Powód odejścia przychodzi tylko do Kadr i przełożonego.
//
// Etap 3 (17.10.2026): ścieżki mają odbiorców (zespół wewnętrzny / konsultant
// u klienta), wersje i warunki pozycji; wejście konsultanta to lista przy
// kontrakcie (`/contracts/{id}/entry`) ze ścieżki, pakietu klienta i formy.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { hrKeys, type EmploymentType, type WorkLocation } from "@/lib/api/hr";

export type CaseKind = "onboarding" | "offboarding";
export type CaseStatus = "draft" | "active" | "done" | "cancelled";
export type CaseScope = "admin" | "manager" | "assignee" | "viewer";
export type Audience = "team" | "consultant";
export type TaskSource = "path" | "client" | "form" | "manual";
export type TaskCategory =
  | "accounts"
  | "equipment"
  | "documents"
  | "training"
  | "meeting"
  | "other";
export type AssigneeKind =
  | "manager"
  | "people_admin"
  | "reception"
  | "person"
  | "it"
  | "care_owner"
  | "delivery_lead"
  | "administration";
export type TaskStatus = "open" | "done" | "skipped";
export type ExitInitiator = "employee" | "company" | "mutual";
export type ExitReason =
  | "new_opportunity"
  | "compensation"
  | "role_fit"
  | "management"
  | "work_life_balance"
  | "career_growth"
  | "relocation"
  | "contract_end"
  | "other";
export type WorkKind =
  | "recruitments"
  | "pipeline_cards"
  | "client_meetings"
  | "followups"
  | "my_people"
  | "delivery_lead_jobs"
  | "dl_clients"
  | "reports"
  | "care"
  | "substitutions";
export type TransferKind =
  | "recruitments"
  | "delivery_lead_jobs"
  | "dl_clients"
  | "my_people"
  | "reports"
  | "care";
export type HandoverStatus = "planned" | "done" | "failed";
export type AccountCloseResult = "deactivated" | "already_inactive" | "skipped_admin";

export interface LifecycleTask {
  id: number;
  title: string;
  category: TaskCategory;
  assignee_kind: AssigneeKind;
  assignee_user_id: number | null;
  assignee_name: string | null;
  due_date: string | null;
  status: TaskStatus;
  overdue: boolean;
  done_at: string | null;
  done_by_name: string | null;
  note: string | null;
  description?: string | null;
  required?: boolean;
  requires_file?: boolean;
  /** Stały klucz pozycji ścieżki (np. `welcome_mail`). */
  key?: string | null;
  source?: TaskSource;
  /** Nazwa klienta albo forma przy zadaniu z pakietu lub formy. */
  source_label?: string | null;
  from_template: boolean;
  /** Zadanie prowadzi inny moduł (zestaw sprzętu odhacza recepcja w Sprzęcie). */
  mirror?: { module: "equipment"; task_id: number; status: TaskStatus; note: string } | null;
  can_toggle: boolean;
}

export interface WorkRow {
  kind: WorkKind;
  label: string;
  note: string;
  transferable: boolean;
  /** Stan na teraz; `null` w liście spraw (liczone tylko w szczegółach). */
  count: number | null;
  receiver_user_id: number | null;
  receiver_name: string | null;
  status: HandoverStatus | null;
  planned_count: number | null;
  result: Record<string, number> | null;
  error: string | null;
}

export interface CaseProgress {
  done: number;
  total: number;
  overdue: number;
}

export interface OnboardingProfileValues {
  employment_type?: EmploymentType;
  hired_on?: string | null;
  default_location?: WorkLocation;
  timesheet_required?: boolean;
  can_log_overtime?: boolean;
  job_title?: string | null;
  department?: string | null;
  phone?: string | null;
  manager_user_id?: number | null;
  work_start_date?: string | null;
}

export interface LifecycleCase {
  id: number;
  kind: CaseKind;
  status: CaseStatus;
  user_id: number | null;
  person_name: string;
  pending_email: string | null;
  template_id: number | null;
  template_name: string | null;
  audience?: Audience;
  contract_id?: number | null;
  template_version?: number | null;
  template_current_version?: number | null;
  start_date: string | null;
  last_working_day: string | null;
  deactivate_on: string | null;
  handover_at: string | null;
  manager_user_id: number | null;
  manager_name: string | null;
  owner_name: string | null;
  started_at: string | null;
  handover_executed_at: string | null;
  account_closed_at: string | null;
  account_close_result: AccountCloseResult | null;
  completed_at: string | null;
  cancelled_at: string | null;
  scope: CaseScope;
  can_manage: boolean;
  can_cancel: boolean;
  can_add_task?: boolean;
  tasks: LifecycleTask[];
  progress: CaseProgress;
  exit_initiator?: ExitInitiator | null;
  exit_reason?: ExitReason | null;
  exit_note?: string | null;
  profile_values?: OnboardingProfileValues;
  work?: WorkRow[];
}

export type EquipmentCondition = "ours" | "client";

/** Warunki pozycji ścieżki (puste = zawsze). */
export interface ItemConditions {
  employment_types?: EmploymentType[];
  equipment?: EquipmentCondition | null;
  student?: boolean | null;
}

export interface TemplateItem {
  id?: number;
  title: string;
  category: TaskCategory;
  assignee_kind: AssigneeKind;
  due_offset_days: number;
  description?: string | null;
  required?: boolean;
  requires_file?: boolean;
  conditions?: ItemConditions;
  /** Tylko z serwera — formularz go nie zmienia. */
  key?: string | null;
  added_in_version?: number;
}

export interface LifecycleTemplate {
  id: number;
  kind: CaseKind;
  audience?: Audience;
  version?: number;
  name: string;
  is_active: boolean;
  employment_type: EmploymentType | null;
  department: string | null;
  /** Czy oglądający może zmienić tę ścieżkę (O4). */
  can_edit?: boolean;
  /** Trwające sprawy na starszej wersji („Dociągnij”). */
  live_cases_behind?: number;
  items: TemplateItem[];
}

export interface TemplateInput {
  kind: CaseKind;
  audience?: Audience;
  name: string;
  is_active: boolean;
  employment_type: EmploymentType | null;
  department: string | null;
  items: TemplateItem[];
}

export interface PreviewTask {
  title: string;
  category: TaskCategory;
  assignee_kind: AssigneeKind;
  due_date: string;
}

export interface PersonLifecycleSummary {
  case: {
    id: number;
    kind: CaseKind;
    status: CaseStatus;
    start_date: string | null;
    last_working_day: string | null;
    deactivate_on: string | null;
    handover_executed_at: string | null;
    account_closed_at: string | null;
    account_close_result: AccountCloseResult | null;
    progress: CaseProgress;
    link: string;
  } | null;
  can_manage: boolean;
}

export interface OnboardingInput {
  user_id?: number | null;
  email?: string | null;
  name?: string | null;
  start_date: string;
  template_id?: number | null;
  manager_user_id?: number | null;
  profile: OnboardingProfileValues;
  start: boolean;
}

export interface OffboardingInput {
  user_id: number;
  last_working_day: string;
  exit_initiator?: ExitInitiator | null;
  exit_reason?: ExitReason | null;
  exit_note?: string | null;
  manager_user_id?: number | null;
  template_id?: number | null;
  start: boolean;
}

export const CASE_STATUS_LABELS: Record<CaseStatus, string> = {
  draft: "Szkic",
  active: "W toku",
  done: "Zakończona",
  cancelled: "Anulowana",
};

export const CATEGORY_LABELS: Record<TaskCategory, string> = {
  accounts: "Konta",
  equipment: "Sprzęt",
  documents: "Dokumenty",
  training: "Szkolenie",
  meeting: "Rozmowa",
  other: "Inne",
};

export const ASSIGNEE_LABELS: Record<AssigneeKind, string> = {
  manager: "Przełożony",
  people_admin: "Kadry",
  reception: "Recepcja",
  person: "Osoba",
  it: "IT",
  care_owner: "Opiekun",
  delivery_lead: "DL",
  administration: "Administracja",
};

/** Wykonawcy, których ma sens wybierać przy ścieżce danych odbiorców. */
export const AUDIENCE_ASSIGNEES: Record<Audience, AssigneeKind[]> = {
  team: ["manager", "people_admin", "reception", "it", "person", "administration"],
  consultant: [
    "care_owner",
    "delivery_lead",
    "reception",
    "administration",
    "people_admin",
    "it",
  ],
};

export const AUDIENCE_LABELS: Record<Audience, string> = {
  team: "Zespół wewnętrzny",
  consultant: "Konsultant u klienta",
};

export const TASK_SOURCE_LABELS: Record<TaskSource, string> = {
  path: "ścieżka",
  client: "klient",
  form: "forma",
  manual: "dopisane",
};

export const EXIT_INITIATOR_LABELS: Record<ExitInitiator, string> = {
  employee: "Osoba zrezygnowała",
  company: "Firma zakończyła współpracę",
  mutual: "Za porozumieniem",
};

export const EXIT_REASON_LABELS: Record<ExitReason, string> = {
  new_opportunity: "Nowa praca",
  compensation: "Wynagrodzenie",
  role_fit: "Dopasowanie do roli",
  management: "Współpraca z przełożonym",
  work_life_balance: "Czas pracy i życie prywatne",
  career_growth: "Rozwój",
  relocation: "Przeprowadzka",
  contract_end: "Koniec umowy lub projektu",
  other: "Inny",
};

export const HANDOVER_ERROR_LABELS: Record<string, string> = {
  no_receiver: "Nie wskazano przejmującego.",
  receiver_inactive: "Przejmujący nie ma aktywnego konta.",
  receiver_not_eligible: "Przejmujący nie ma roli, której wymaga ta praca.",
  receiver_is_leaver: "Osoba odchodząca nie przejmie własnej pracy.",
  receiver_leaving:
    "Przejmujący sam odchodzi — jego ostatni dzień pracy wypada najpóźniej w dniu przekazania.",
  receiver_creates_loop:
    "Przejmujący podlega jednej z tych osób — wybierz kogoś spoza zespołu odchodzącego albo z jego bezpośrednich podwładnych.",
  receiver_out_of_scope:
    "Przejmujący nie ma części tych klientów w portfelu — wybierz head back office, Talent Community Managera albo administratora.",
  receiver_excluded: "Tej osobie nie przypisujemy konsultantów (pula opiekunów) — wybierz kogoś innego.",
  error: "Przekazanie nie wyszło — Kadry dostały dzwonek.",
};

const BASE = "/api/hr/lifecycle";

/** Ładunek podglądu zadań (`POST /preview`) — także część klucza zapytania. */
export interface PreviewTasksPayload {
  kind: CaseKind;
  anchor: string;
  template_id?: number | null;
  employment_type?: EmploymentType | null;
  department?: string | null;
}

export const lifecycleKeys = {
  all: ["hr", "lifecycle"] as const,
  templates: (kind: CaseKind | null) => ["hr", "lifecycle", "templates", kind] as const,
  cases: (kind: CaseKind | null) => ["hr", "lifecycle", "cases", kind] as const,
  case: (id: number) => ["hr", "lifecycle", "case", id] as const,
  receivers: (id: number, kind: TransferKind) =>
    ["hr", "lifecycle", "receivers", id, kind] as const,
  summary: (userId: number) => ["hr", "lifecycle", "summary", userId] as const,
  myTasks: ["hr", "lifecycle", "my-tasks"] as const,
  contractEntry: (contractId: number) =>
    ["hr", "lifecycle", "contract-entry", contractId] as const,
  preview: (payload: PreviewTasksPayload) => ["hr", "lifecycle", "preview", payload] as const,
};

function useInvalidateLifecycle() {
  const queryClient = useQueryClient();
  // Kartoteka (status, ostatni dzień) też się zmienia — odśwież cały obszar.
  return () => queryClient.invalidateQueries({ queryKey: hrKeys.all });
}

export function useLifecycleTemplates(kind: CaseKind | null, enabled = true) {
  return useQuery({
    queryKey: lifecycleKeys.templates(kind),
    queryFn: async () =>
      (
        await api.get<{ items: LifecycleTemplate[] }>(`${BASE}/templates`, {
          params: kind ? { kind } : undefined,
        })
      ).data.items,
    enabled,
  });
}

export function useSaveTemplate() {
  const invalidate = useInvalidateLifecycle();
  return useMutation({
    mutationFn: async ({ id, ...payload }: TemplateInput & { id?: number }) =>
      id
        ? (await api.put<LifecycleTemplate>(`${BASE}/templates/${id}`, payload)).data
        : (await api.post<LifecycleTemplate>(`${BASE}/templates`, payload)).data,
    onSuccess: invalidate,
  });
}

export function usePreviewTasks(input: PreviewTasksPayload & { enabled: boolean }) {
  const { enabled, ...payload } = input;
  return useQuery({
    queryKey: lifecycleKeys.preview(payload),
    queryFn: async () =>
      (
        await api.post<{
          template_id: number | null;
          template_name: string | null;
          tasks: PreviewTask[];
        }>(`${BASE}/preview`, payload)
      ).data,
    enabled: enabled && Boolean(payload.anchor),
  });
}

export function useLifecycleCases(kind: CaseKind | null, enabled = true) {
  return useQuery({
    queryKey: lifecycleKeys.cases(kind),
    queryFn: async () =>
      (
        await api.get<{ items: LifecycleCase[]; total: number }>(`${BASE}/cases`, {
          params: kind ? { kind } : undefined,
        })
      ).data,
    enabled,
  });
}

export function useLifecycleCase(caseId: number | null) {
  return useQuery({
    queryKey: lifecycleKeys.case(caseId ?? 0),
    queryFn: async () =>
      (await api.get<LifecycleCase>(`${BASE}/cases/${caseId}`)).data,
    enabled: caseId != null && Number.isFinite(caseId) && caseId > 0,
  });
}

export function usePersonLifecycleSummary(userId: number, enabled = true) {
  return useQuery({
    queryKey: lifecycleKeys.summary(userId),
    queryFn: async () =>
      (await api.get<PersonLifecycleSummary>(`${BASE}/people/${userId}/summary`)).data,
    enabled: enabled && Number.isFinite(userId) && userId > 0,
  });
}

/** Moje zadanie wejścia albo odejścia („Mój czas → Do zrobienia”). */
export interface MyLifecycleTask {
  task_id: number;
  case_id: number;
  kind: CaseKind;
  person_name: string;
  title: string;
  due_date: string | null;
  overdue: boolean;
  link: string;
}

export function useMyLifecycleTasks(enabled = true) {
  return useQuery({
    queryKey: lifecycleKeys.myTasks,
    queryFn: async () =>
      (await api.get<{ items: MyLifecycleTask[] }>(`${BASE}/my-tasks`)).data.items,
    enabled,
  });
}

export function useCreateOnboarding() {
  const invalidate = useInvalidateLifecycle();
  return useMutation({
    mutationFn: async (payload: OnboardingInput) =>
      (await api.post<LifecycleCase>(`${BASE}/cases/onboarding`, payload)).data,
    onSuccess: invalidate,
  });
}

export function useCreateOffboarding() {
  const invalidate = useInvalidateLifecycle();
  return useMutation({
    mutationFn: async (payload: OffboardingInput) =>
      (await api.post<LifecycleCase>(`${BASE}/cases/offboarding`, payload)).data,
    onSuccess: invalidate,
  });
}

export interface CaseUpdateInput {
  start_date?: string;
  last_working_day?: string;
  manager_user_id?: number | null;
  template_id?: number | null;
  exit_initiator?: ExitInitiator | null;
  exit_reason?: ExitReason | null;
  exit_note?: string | null;
  pending_name?: string | null;
  profile?: OnboardingProfileValues;
}

export function useUpdateCase(caseId: number) {
  const invalidate = useInvalidateLifecycle();
  return useMutation({
    mutationFn: async (payload: CaseUpdateInput) =>
      (await api.patch<LifecycleCase>(`${BASE}/cases/${caseId}`, payload)).data,
    onSuccess: invalidate,
  });
}

export type CaseAction = "start" | "cancel" | "complete" | "deactivate-now";

export function useCaseAction(caseId: number) {
  const invalidate = useInvalidateLifecycle();
  return useMutation({
    mutationFn: async (action: CaseAction) =>
      (await api.post<LifecycleCase>(`${BASE}/cases/${caseId}/${action}`)).data,
    onSuccess: invalidate,
  });
}

/**
 * „Wyłącz konto teraz”. Serwer odmawia (409), dopóki praca nie jest przekazana;
 * `despiteHandover` = jawna decyzja Kadr „wyłącz mimo to” (zapisana w śladzie).
 */
export function useDeactivateNow(caseId: number) {
  const invalidate = useInvalidateLifecycle();
  return useMutation({
    mutationFn: async (despiteHandover: boolean) =>
      (
        await api.post<LifecycleCase>(`${BASE}/cases/${caseId}/deactivate-now`, null, {
          params: despiteHandover ? { despite_handover: true } : undefined,
        })
      ).data,
    onSuccess: invalidate,
  });
}

export function useSetReceivers(caseId: number) {
  const invalidate = useInvalidateLifecycle();
  return useMutation({
    mutationFn: async (receivers: Partial<Record<TransferKind, number | null>>) =>
      (await api.put<LifecycleCase>(`${BASE}/cases/${caseId}/handovers`, { receivers }))
        .data,
    onSuccess: invalidate,
  });
}

export function useReceivers(caseId: number, kind: TransferKind, enabled = true) {
  return useQuery({
    queryKey: lifecycleKeys.receivers(caseId, kind),
    queryFn: async () =>
      (
        await api.get<{ items: { user_id: number; name: string }[] }>(
          `${BASE}/cases/${caseId}/receivers`,
          { params: { kind } },
        )
      ).data.items,
    enabled,
    staleTime: 60 * 1000,
  });
}

export function useAddTask(caseId: number) {
  const invalidate = useInvalidateLifecycle();
  return useMutation({
    mutationFn: async (payload: {
      title: string;
      category: TaskCategory;
      assignee_kind: AssigneeKind;
      due_date: string | null;
    }) => (await api.post<LifecycleCase>(`${BASE}/cases/${caseId}/tasks`, payload)).data,
    onSuccess: invalidate,
  });
}

export function useUpdateTask() {
  const invalidate = useInvalidateLifecycle();
  return useMutation({
    mutationFn: async ({
      taskId,
      ...payload
    }: {
      taskId: number;
      status?: TaskStatus;
      note?: string | null;
    }) => (await api.patch<LifecycleCase>(`${BASE}/tasks/${taskId}`, payload)).data,
    onSuccess: invalidate,
  });
}

// ── Etap 3: ścieżki z wersjami i wejście konsultanta przy kontrakcie ─────────

export function useCatchUpTemplate() {
  const invalidate = useInvalidateLifecycle();
  return useMutation({
    mutationFn: async (templateId: number) =>
      (
        await api.post<{ cases: number; tasks: number; template: LifecycleTemplate }>(
          `${BASE}/templates/${templateId}/catch-up`,
        )
      ).data,
    onSuccess: invalidate,
  });
}

export type EntryMissingReason =
  | "past_start"
  | "no_start"
  | "closed"
  | "no_path"
  | "not_yet"
  | "module_off";

/** Karta „Z czego to powstało” (M6). */
export interface EntryComposition {
  client_id: number;
  client_name: string | null;
  employment_type: EmploymentType | null;
  employment_label: string | null;
  equipment: EquipmentCondition | null;
  care_owner: { id: number; name: string | null; source: string | null } | null;
  delivery_lead: { id: number; name: string | null } | null;
  client_manager: string | null;
}

/** `GET /api/hr/lifecycle/contracts/{id}/entry` — zakładka „Wejście” kontraktu. */
export interface ContractEntryView {
  contract_id: number;
  module_on: boolean;
  start_date: string | null;
  case: LifecycleCase | null;
  composition: EntryComposition;
  missing_reason: EntryMissingReason | null;
  /** Dzień, w którym lista założy się sama (14 dni przed startem). */
  auto_create_on?: string | null;
  /** Pakiet klienta nie wczytał się przy zakładaniu — pozycje dojdą później. */
  pack_failed?: boolean;
  can_create: boolean;
  can_add_task: boolean;
  /** Stare pozycje `contract_onboarding_items` (tylko do odczytu). */
  legacy_items: number;
}

export function useContractEntry(contractId: number, enabled = true) {
  return useQuery({
    queryKey: lifecycleKeys.contractEntry(contractId),
    queryFn: async () =>
      (await api.get<ContractEntryView>(`${BASE}/contracts/${contractId}/entry`)).data,
    enabled: enabled && Number.isFinite(contractId) && contractId > 0,
  });
}

export function useCreateContractEntry(contractId: number) {
  const invalidate = useInvalidateLifecycle();
  return useMutation({
    mutationFn: async () =>
      (await api.post<ContractEntryView>(`${BASE}/contracts/${contractId}/entry`)).data,
    onSuccess: invalidate,
  });
}

export function useAddContractEntryTask(contractId: number) {
  const invalidate = useInvalidateLifecycle();
  return useMutation({
    mutationFn: async (payload: {
      title: string;
      category: TaskCategory;
      assignee_kind: AssigneeKind;
      due_date: string | null;
      description?: string | null;
    }) =>
      (
        await api.post<ContractEntryView>(
          `${BASE}/contracts/${contractId}/entry/tasks`,
          payload,
        )
      ).data,
    onSuccess: invalidate,
  });
}
