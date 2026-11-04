// Przepięcie kontraktu na innego klienta (tylko admin).
//
// Lustro `backend/app/api/contract_client_reassign.py`. Podgląd liczy serwer
// (co przejdzie, co blokuje) i oddaje odcisk; wykonanie z innym odciskiem to
// 409 — admin zatwierdzał inny stan świata.

import { api } from "@/lib/api";

export interface ReassignClientRef {
  id: number;
  name: string;
}

export interface ReassignOrderRow {
  id: number;
  title: string;
  status: string;
  client_id: number;
  start_date: string | null;
  end_date: string | null;
}

export interface ReassignBlocker {
  code: string;
  ids?: number[];
  message: string;
}

export interface ReassignPlan {
  contract_id: number;
  contract_label: string;
  contract_status: string;
  from_client: ReassignClientRef;
  to_client: ReassignClientRef;
  orders: ReassignOrderRow[];
  b2b_documents: { id: number; contract_number: string; contract_status: string; printed_client_name: string | null }[];
  // Aneksy i rozwiązania przenoszonych umów B2B (runda 6 audytu, REA-1).
  b2b_derived_documents?: { id: number; document_type: string; parent_generated_contract_id: number | null }[];
  open_gaps: { id: number; order_number: string | null; ended_on: string }[];
  alerts: { id: number; alert_type: string; title: string }[];
  blockers: ReassignBlocker[];
  warnings: { code: string; message: string }[];
  can_apply: boolean;
  fingerprint: string;
}

export const contractReassignKeys = {
  preview: (contractId: number, clientId: number | null) =>
    ["contract-client-reassign", contractId, clientId] as const,
};

export async function fetchReassignPreview(contractId: number, clientId: number): Promise<ReassignPlan> {
  const { data } = await api.get<ReassignPlan>(`/api/contracts/${contractId}/client-reassign-preview`, {
    params: { client_id: clientId },
  });
  return data;
}

export async function applyReassign(contractId: number, clientId: number, fingerprint: string): Promise<ReassignPlan> {
  const { data } = await api.post<ReassignPlan>(`/api/contracts/${contractId}/client-reassign`, {
    client_id: clientId,
    fingerprint,
  });
  return data;
}

/** Plan z odpowiedzi 409 (blokery albo zmieniony odcisk) — żeby okno pokazało aktualny stan. */
export function planFromConflict(error: unknown): ReassignPlan | null {
  const detail = (error as { response?: { status?: number; data?: { detail?: unknown } } } | null)?.response;
  if (detail?.status !== 409) return null;
  const body = detail.data?.detail;
  if (body && typeof body === "object" && "plan" in body) {
    const plan = (body as { plan?: unknown }).plan;
    if (plan && typeof plan === "object" && "fingerprint" in plan) return plan as ReassignPlan;
  }
  return null;
}
