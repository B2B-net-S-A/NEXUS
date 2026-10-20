// Zgody na wydatki i premie poza umową (0483, decyzja Artura 20.10.2026).
//
// Lustro `backend/app/api/hr_approvals.py`. Drogę zgody (przełożony do progu,
// ponad próg zatwierdzający), kto widzi i kto decyduje liczy serwer; front
// pokazuje, co dostał (`can_decide`, `decides_as`, `can_edit`). Premie z umowy
// (placementy, ligi, reguły Płac) nie przechodzą przez zgody.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { HR_COUNTS_MUTATION_KEY, hrKeys } from "@/lib/api/hr";

const ROOT = "/api/hr/approval-requests";

export type ApprovalKind = "bonus" | "subscription" | "trip" | "gift" | "training" | "other";
export type ApprovalStatus =
  "pending_supervisor" | "pending_final" | "approved" | "rejected" | "returned" | "withdrawn";
export type ApprovalRecurrence = "once" | "monthly" | "yearly";
export type ApprovalPayer = "company_invoice" | "company_card" | "reimbursement";
export type ApprovalDecision = "approve" | "reject" | "return";

export interface ApprovalContextSum {
  count: number;
  amount: string;
}

export interface ApprovalContext {
  kind_month: ApprovalContextSum;
  kind_year: ApprovalContextSum;
  all_month: ApprovalContextSum;
  beneficiary_year?: {
    automatic: string;
    outside_contract: string;
    manual: string;
    same_month_automatic: string;
  };
}

export interface ApprovalRequestRow {
  id: number;
  kind: ApprovalKind;
  kind_label: string;
  status: ApprovalStatus;
  status_label: string;
  title: string;
  purpose: string;
  amount: string;
  decided_amount: string | null;
  currency: string;
  amount_basis: "gross" | "net";
  recurrence: ApprovalRecurrence;
  amount_text: string;
  payer: ApprovalPayer | null;
  link_url: string | null;
  needed_by: string | null;
  starts_on: string | null;
  ends_on: string | null;
  beneficiary_user_id: number | null;
  beneficiary_name: string | null;
  payout_year: number | null;
  payout_month: number | null;
  requester_user_id: number;
  requester_name: string | null;
  supervisor_user_id: number | null;
  supervisor_name: string | null;
  needs_final: boolean;
  final_approver_names: string[];
  endorsed_by_name: string | null;
  endorsed_at: string | null;
  endorse_note: string | null;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_note: string | null;
  decision_channel: string | null;
  bonus_id: number | null;
  submitted_at: string | null;
  can_decide: boolean;
  /** Przełożony ponad próg popiera, nie zatwierdza. */
  decides_as: "final" | "supervisor" | null;
  can_edit: boolean;
  can_withdraw: boolean;
  /** Tylko w szczególe (`GET /{id}`) i tylko dla decydującego. */
  context?: ApprovalContext | null;
}

export interface ApprovalRequestInput {
  kind: ApprovalKind;
  title: string;
  purpose: string;
  amount: string;
  currency: string;
  amount_basis: "gross" | "net";
  recurrence: ApprovalRecurrence;
  payer: ApprovalPayer | null;
  link_url: string | null;
  needed_by: string | null;
  starts_on: string | null;
  ends_on: string | null;
  beneficiary_user_id: number | null;
  payout_year: number | null;
  payout_month: number | null;
}

export interface ApprovalRoutePreview {
  supervisor_name: string | null;
  supervisor_decides_alone: boolean;
  final_approver_names: string[];
  supervisor_limit: number | null;
}

export interface ApprovalRules {
  final_approver_user_id: number | null;
  supervisor_limits: Record<ApprovalKind, number | null>;
  defaults: Record<ApprovalKind, number | null>;
  effective_final_approver_names: string[];
}

export const approvalKeys = {
  all: ["hr", "approval-requests"] as const,
  list: (scope: "inbox" | "mine" | "decided") =>
    ["hr", "approval-requests", "list", scope] as const,
  detail: (id: number) => ["hr", "approval-requests", "detail", id] as const,
  count: ["hr", "approval-requests", "count"] as const,
  beneficiaries: ["hr", "approval-requests", "beneficiaries"] as const,
  rules: ["hr", "approval-requests", "rules"] as const,
};

function parseCount(raw: unknown): number {
  const value = (raw as { inbox?: unknown } | null)?.inbox;
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new Error("Nieoczekiwana odpowiedź licznika zgód.");
  }
  return value;
}

function parseItems(raw: unknown): ApprovalRequestRow[] {
  const items = (raw as { items?: unknown } | null)?.items;
  if (!Array.isArray(items)) throw new Error("Nieoczekiwana odpowiedź listy zgód.");
  return items as ApprovalRequestRow[];
}

export function useApprovalList(scope: "inbox" | "mine" | "decided", enabled = true) {
  return useQuery({
    queryKey: approvalKeys.list(scope),
    queryFn: async () => parseItems((await api.get<unknown>(ROOT, { params: { scope } })).data),
    enabled,
  });
}

export function useApprovalDetail(id: number | null) {
  return useQuery({
    queryKey: approvalKeys.detail(id ?? 0),
    queryFn: async () => (await api.get<ApprovalRequestRow>(`${ROOT}/${id}`)).data,
    enabled: id !== null,
  });
}

/** Licznik ikony „Zgody” — tylko przy działającym module (inaczej 404). */
export function useApprovalCount(enabled: boolean) {
  return useQuery({
    queryKey: approvalKeys.count,
    queryFn: async () => parseCount((await api.get<unknown>(`${ROOT}/count`)).data),
    enabled,
    staleTime: 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
    retry: false,
  });
}

export function useApprovalBeneficiaries(enabled: boolean) {
  return useQuery({
    queryKey: approvalKeys.beneficiaries,
    queryFn: async () =>
      (await api.get<{ items: { user_id: number; name: string }[] }>(`${ROOT}/beneficiaries`)).data
        .items,
    enabled,
    staleTime: 5 * 60 * 1000,
  });
}

export function useApprovalRoutePreview() {
  return useMutation({
    mutationFn: async (input: ApprovalRequestInput) =>
      (await api.post<ApprovalRoutePreview>(`${ROOT}/preview`, input)).data,
  });
}

function useInvalidateApprovals() {
  const queryClient = useQueryClient();
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: approvalKeys.all }),
      queryClient.invalidateQueries({ queryKey: hrKeys.counts }),
    ]);
  };
}

export function useSubmitApproval() {
  const invalidate = useInvalidateApprovals();
  return useMutation({
    mutationFn: async (input: ApprovalRequestInput) =>
      (await api.post<ApprovalRequestRow>(ROOT, input)).data,
    onSuccess: invalidate,
  });
}

export function useResubmitApproval() {
  const invalidate = useInvalidateApprovals();
  return useMutation({
    mutationFn: async ({ id, input }: { id: number; input: ApprovalRequestInput }) =>
      (await api.put<ApprovalRequestRow>(`${ROOT}/${id}`, input)).data,
    onSuccess: invalidate,
  });
}

export function useWithdrawApproval() {
  const invalidate = useInvalidateApprovals();
  return useMutation({
    mutationFn: async (id: number) =>
      (await api.post<ApprovalRequestRow>(`${ROOT}/${id}/withdraw`)).data,
    onSuccess: invalidate,
  });
}

export function useDecideApproval() {
  const invalidate = useInvalidateApprovals();
  return useMutation({
    // Licznik „Akceptacji” liczy się od nowa po decyzji.
    mutationKey: [...HR_COUNTS_MUTATION_KEY, "approval-decision"],
    mutationFn: async ({
      id,
      action,
      amount,
      note,
    }: {
      id: number;
      action: ApprovalDecision;
      amount?: string | null;
      note?: string | null;
    }) =>
      (
        await api.post<ApprovalRequestRow>(`${ROOT}/${id}/decide`, {
          action,
          amount: amount ?? null,
          note: note ?? null,
        })
      ).data,
    onSuccess: invalidate,
  });
}

export function useApprovalRules(enabled: boolean) {
  return useQuery({
    queryKey: approvalKeys.rules,
    queryFn: async () => (await api.get<ApprovalRules>(`${ROOT}/rules`)).data,
    enabled,
  });
}

export function useSaveApprovalRules() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      final_approver_user_id: number | null;
      supervisor_limits: Record<ApprovalKind, number | null>;
    }) => (await api.put<ApprovalRules>(`${ROOT}/rules`, input)).data,
    onSuccess: (data) => queryClient.setQueryData(approvalKeys.rules, data),
  });
}
