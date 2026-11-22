// „Przepisy” (/compliance, 15.11.2026): radar zmian w prawie.
//
// Lustro `backend/app/api/law_radar.py`. Dostęp: admin i Head of Recruitment
// z roli, reszta z „Moduł Finanse”, „Płace”, „Kadry” albo „Kontrakty
// i zamówienia” (`lib/compliance-access.ts`). Przy wyłączonym
// `LAW_RADAR_ENABLED` odczyty dają `{enabled: false}`, zapisy 409.
// Ręczny start Zbieracza tylko admin.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

const BASE = "/api/compliance";

export type ComplianceRole = "board" | "accounting" | "payroll" | "contracts" | "recruitment";
export type ChangeUrgency = "now" | "soon" | "watch";
export type ChangeStage = "project" | "sejm" | "senate" | "president" | "journal" | "in_force";
export type ChangeStatus = "new" | "in_progress" | "done" | "not_applicable";
export type ItemClass = "official" | "lex" | "practice";
export type ItemGate = "pending" | "verified" | "unverified" | "rejected";
export type RunKind = "collect" | "analyze";
export type RunStatus = "started" | "received" | "failed" | "expired";

export interface ChangeProbe {
  key: string;
  value: number | null;
  text: string | null;
  link: string | null;
  computed_at: string | null;
}

export interface LawChangeRow {
  id: number;
  title: string;
  summary: string[];
  roles: ComplianceRole[];
  urgency: ChangeUrgency;
  stage: ChangeStage;
  effective_on: string | null;
  deadline: string | null;
  legal_ref: string | null;
  status: ChangeStatus;
  decision_note: string | null;
  decided_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface LawChangeListItem extends LawChangeRow {
  verified_sources?: number;
  probes: ChangeProbe[];
  tasks: { open: number; done: number };
}

export type ChangeList =
  | { enabled: false; changes: [] }
  | { enabled: true; changes: LawChangeListItem[] };

export interface ChangeItem {
  id: number;
  source: string;
  klass: ItemClass;
  gate: ItemGate;
  title: string;
  url: string;
  published: string | null;
  act_ref: string | null;
  print_no: string | null;
  stage: string | null;
  quote: string | null;
  official: Record<string, unknown>;
}

export interface ChangeTask {
  id: number;
  text: string;
  role: ComplianceRole | null;
  source: "bot" | "user";
  assignee: { id: number; name: string | null } | null;
  due_on: string | null;
  done: boolean;
  done_at: string | null;
}

export type ChangeEventKind =
  | "created"
  | "updated"
  | "stage"
  | "status"
  | "task_added"
  | "task_done"
  | "task_reopened"
  | "task_updated";

export interface ChangeEvent {
  id: number;
  kind: ChangeEventKind;
  from: string | null;
  to: string | null;
  note: string | null;
  task_id: number | null;
  by: string | null;
  bot: boolean;
  at: string;
}

export interface ChangeDetail {
  enabled: true;
  change: LawChangeRow & { decided_by: string | null };
  items: ChangeItem[];
  tasks: ChangeTask[];
  events: ChangeEvent[];
  probes: ChangeProbe[];
}

export type ChangeDetailResponse = { enabled: false } | ChangeDetail;

export interface SummaryTop {
  id: number;
  title: string;
  urgency: ChangeUrgency;
  deadline: string | null;
}

export type ComplianceSummary =
  | { enabled: false; to_decide: 0; deadlines: 0; top: [] }
  | {
      enabled: true;
      to_decide: number;
      deadlines: number;
      deadline_window_days: number;
      top: SummaryTop[];
    };

/** Liczniki i kody przyczyn pominięcia źródeł, bez treści raportu. */
export type RunSummary = Record<string, number | boolean | string | Record<string, number | boolean>>;

export interface RadarRun {
  id: number;
  kind: RunKind;
  status: RunStatus;
  started_at: string | null;
  received_at: string | null;
  error: string | null;
  summary: RunSummary;
}

export interface RunList {
  enabled: boolean;
  configured: Record<RunKind, boolean>;
  runs: RadarRun[];
}

export interface TaskInput {
  text: string;
  role?: ComplianceRole | null;
  due_on?: string | null;
}

export const complianceKeys = {
  all: ["compliance"] as const,
  changes: (role: ComplianceRole | null) => ["compliance", "changes", role ?? "all"] as const,
  change: (id: number) => ["compliance", "change", id] as const,
  summary: (role: ComplianceRole | null) => ["compliance", "summary", role ?? "all"] as const,
  runs: ["compliance", "runs"] as const,
};

export function useComplianceChanges(role: ComplianceRole | null) {
  return useQuery({
    queryKey: complianceKeys.changes(role),
    queryFn: async () =>
      (await api.get<ChangeList>(`${BASE}/changes`, { params: { role: role ?? undefined } })).data,
    placeholderData: (previous) => previous,
  });
}

export function useComplianceChange(id: number | null) {
  return useQuery({
    queryKey: complianceKeys.change(id ?? 0),
    queryFn: async () => (await api.get<ChangeDetailResponse>(`${BASE}/changes/${id}`)).data,
    enabled: id != null && id > 0,
  });
}

export function useComplianceSummary(role: ComplianceRole | null, enabled = true) {
  return useQuery({
    queryKey: complianceKeys.summary(role),
    queryFn: async () =>
      (await api.get<ComplianceSummary>(`${BASE}/summary`, { params: { role: role ?? undefined } }))
        .data,
    staleTime: 5 * 60 * 1000,
    enabled,
  });
}

export function useComplianceRuns() {
  return useQuery({
    queryKey: complianceKeys.runs,
    queryFn: async () => (await api.get<RunList>(`${BASE}/runs`)).data,
    staleTime: 60 * 1000,
  });
}

/** Decyzja i zadanie zmieniają listę, szczegół, liczniki paska i terminy naraz. */
function useInvalidateCompliance() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: complianceKeys.all });
}

export function useDecideChange() {
  const invalidate = useInvalidateCompliance();
  return useMutation({
    mutationFn: async (args: { id: number; status: ChangeStatus; note?: string | null }) =>
      (
        await api.patch<{ enabled: true; change: LawChangeRow }>(`${BASE}/changes/${args.id}`, {
          status: args.status,
          note: args.note ?? undefined,
        })
      ).data,
    onSuccess: () => invalidate(),
  });
}

export function useAddChangeTask(changeId: number) {
  const invalidate = useInvalidateCompliance();
  return useMutation({
    mutationFn: async (body: TaskInput) =>
      (await api.post<ChangeTask>(`${BASE}/changes/${changeId}/tasks`, body)).data,
    onSuccess: () => invalidate(),
  });
}

export function useUpdateChangeTask() {
  const invalidate = useInvalidateCompliance();
  return useMutation({
    mutationFn: async (args: { id: number; done: boolean }) =>
      (await api.patch<ChangeTask>(`${BASE}/tasks/${args.id}`, { done: args.done })).data,
    onSettled: () => invalidate(),
  });
}

export function useStartCollect() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.post<RadarRun>(`${BASE}/runs/collect`)).data,
    onSuccess: () => client.invalidateQueries({ queryKey: complianceKeys.runs }),
  });
}
