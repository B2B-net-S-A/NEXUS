// Zgody na wydatki i premie poza umową (0483, decyzja Artura 20.10.2026).
//
// Lustro `backend/app/api/hr_approvals.py`. Drogę zgody (przełożony do progu,
// ponad próg zatwierdzający), kto widzi i kto decyduje liczy serwer; front
// pokazuje, co dostał (`can_decide`, `decides_as`, `can_edit`). Premie z umowy
// (placementy, ligi, reguły Płac) nie przechodzą przez zgody.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { downloadBlob, fetchAuthenticatedDownload } from "@/lib/authenticated-files";
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

/** Porównanie dokumentów z kwotą zgody (próg +10%, etap 3 — 0485). */
export interface ApprovalComparison {
  status: "fits" | "over" | "unknown";
  approved: string;
  documented: string | null;
  limit: string;
  excess: string | null;
  percent: number | null;
}

export type ApprovalDocumentStatus = "pinned" | "settled" | "unmatched" | "fixed_cost" | "dismissed";

export interface ApprovalDocument {
  id: number;
  source: "upload" | "ksef";
  doc_type: "invoice" | "receipt";
  status: ApprovalDocumentStatus;
  status_label: string;
  approval_request_id: number | null;
  match_reason: string | null;
  match_reason_label: string | null;
  ksef_number: string | null;
  seller_nip: string | null;
  seller_name: string | null;
  invoice_number: string | null;
  issue_date: string | null;
  currency: string;
  net_amount: string | null;
  vat_amount: string | null;
  gross_amount: string | null;
  file_name: string | null;
  has_file: boolean;
  read_status: "read" | "failed" | "skipped" | null;
  topup: {
    status: "pending" | "approved" | "rejected";
    amount: string | null;
    requested_at: string | null;
    decided_at: string | null;
    decided_by_name: string | null;
    note: string | null;
  } | null;
  settled_at: string | null;
  settled_by_name: string | null;
  settle_note: string | null;
  close_note: string | null;
  comparison: ApprovalComparison | null;
  can_edit: boolean;
  can_remove: boolean;
  can_request_topup: boolean;
  can_decide_topup: boolean;
  can_settle: boolean;
  /** Tylko w kolejce „Faktury bez zgody”. */
  suggestions?: { id: number; title: string; kind_label: string; amount_text: string; same_seller: boolean }[];
}

export type ApprovalSettlementStatus = "open" | "documented" | "settled" | "expired" | "active" | "ended";

export interface ApprovalSettlement {
  status: ApprovalSettlementStatus;
  status_label: string;
  expires_on: string | null;
  renews_on: string | null;
  renewal_asked_for: string | null;
  renewal_confirmed_for: string | null;
  ended_on: string | null;
  settled_at: string | null;
  settled_by_name: string | null;
  seller_nip: string | null;
  client_id: number | null;
  client_name: string | null;
  tolerance_percent: number;
  comparison: ApprovalComparison | null;
  documents: ApprovalDocument[];
  can_add_document: boolean;
  can_answer_renewal: boolean;
  can_end: boolean;
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
  /** Etap 3 (0485): klient prezentu, znany NIP sprzedawcy, rozliczenie. */
  client_id?: number | null;
  client_name?: string | null;
  seller_nip?: string | null;
  settlement?: ApprovalSettlement | null;
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
  client_id?: number | null;
  seller_nip?: string | null;
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
  topups: ["hr", "approval-requests", "topups"] as const,
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


// ── rozliczenie (etap 3, 0485) ─────────────────────────────────────────────

export interface ApprovalTopupRow {
  request_id: number;
  title: string;
  kind_label: string;
  requester_name: string | null;
  amount_text: string;
  document: ApprovalDocument;
}

export function documentFileUrl(requestId: number, documentId: number): string {
  return `${ROOT}/${requestId}/documents/${documentId}/file`;
}

/** Pobranie faktury albo paragonu (autor, decydujący, Finanse). */
export async function downloadApprovalDocument(
  requestId: number,
  doc: Pick<ApprovalDocument, "id" | "file_name">,
): Promise<void> {
  const { blob, filename } = await fetchAuthenticatedDownload(documentFileUrl(requestId, doc.id));
  downloadBlob(blob, filename ?? doc.file_name ?? "dokument");
}

/** Dopłaty czekające na decyzję zatwierdzającego. */
export function usePendingTopups(enabled = true) {
  return useQuery({
    queryKey: approvalKeys.topups,
    queryFn: async () => {
      const items = (await api.get<{ items?: unknown }>(`${ROOT}/topups`)).data?.items;
      if (!Array.isArray(items)) throw new Error("Nieoczekiwana odpowiedź listy dopłat.");
      return items as ApprovalTopupRow[];
    },
    enabled,
  });
}

function useSettlementMutation<TVars>(
  call: (vars: TVars) => Promise<ApprovalRequestRow>,
  mutationKey?: readonly unknown[],
) {
  const invalidate = useInvalidateApprovals();
  return useMutation({ mutationKey, mutationFn: call, onSuccess: invalidate });
}

export function useUploadApprovalDocument() {
  return useSettlementMutation(async ({ id, file }: { id: number; file: File }) => {
    const form = new FormData();
    form.append("file", file);
    return (await api.post<ApprovalRequestRow>(`${ROOT}/${id}/documents`, form)).data;
  });
}

export interface ApprovalDocumentInput {
  doc_type?: "invoice" | "receipt";
  seller_name?: string | null;
  seller_nip?: string | null;
  invoice_number?: string | null;
  issue_date?: string | null;
  currency?: string;
  net_amount?: string | null;
  vat_amount?: string | null;
  gross_amount?: string | null;
}

export function useUpdateApprovalDocument() {
  return useSettlementMutation(
    async ({ id, documentId, input }: { id: number; documentId: number; input: ApprovalDocumentInput }) =>
      (await api.patch<ApprovalRequestRow>(`${ROOT}/${id}/documents/${documentId}`, input)).data,
  );
}

export function useRemoveApprovalDocument() {
  return useSettlementMutation(
    async ({ id, documentId }: { id: number; documentId: number }) =>
      (await api.delete<ApprovalRequestRow>(`${ROOT}/${id}/documents/${documentId}`)).data,
  );
}

export function useRequestTopup() {
  return useSettlementMutation(
    async ({ id, documentId }: { id: number; documentId: number }) =>
      (await api.post<ApprovalRequestRow>(`${ROOT}/${id}/documents/${documentId}/topup`)).data,
  );
}

export function useDecideTopup() {
  return useSettlementMutation(
    async ({
      id,
      documentId,
      action,
      note,
    }: {
      id: number;
      documentId: number;
      action: "approve" | "reject";
      note?: string | null;
    }) =>
      (
        await api.post<ApprovalRequestRow>(`${ROOT}/${id}/documents/${documentId}/topup/decide`, {
          action,
          note: note ?? null,
        })
      ).data,
    // Licznik „Akceptacji” liczy dopłaty razem ze zgodami.
    [...HR_COUNTS_MUTATION_KEY, "approval-topup"],
  );
}

export function useAnswerRenewal() {
  return useSettlementMutation(
    async ({ id, keep }: { id: number; keep: boolean }) =>
      (await api.post<ApprovalRequestRow>(`${ROOT}/${id}/renewal`, { keep })).data,
  );
}
