// E-faktury Peppol (plan Nordei N2, `docs/rozliczenia-nordea-plan.md`).
//
// Lustro `backend/app/api/client_einvoices.py`
// (`/api/finance/settlements/einvoices…`, moduł Finanse). Kwoty jako tekst
// dziesiętny z kropką.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

const BASE = "/api/finance/settlements/einvoices";

export type EinvoiceStatus =
  | "waiting_xml"
  | "waiting_receiver"
  | "invalid"
  | "ready"
  | "sent"
  | "delivered"
  | "rejected"
  | "skipped";
export type EinvoiceMode = "test" | "production";

export interface EinvoiceProblem {
  rule: string;
  flag: string;
  text: string;
  location: string;
}

export interface EinvoiceHistoryEntry {
  at: string;
  target: EinvoiceMode;
  recipient: string;
  document_id?: string;
  state: string;
  detail?: string | null;
}

export interface EinvoiceRow {
  id: number;
  invoice_id: number;
  invoice_number: string;
  ksef_number: string;
  kind: "original" | "correction";
  issue_date: string;
  period: string | null;
  buyer_name: string | null;
  receiver_name: string;
  currency: string;
  gross_amount: string;
  status: EinvoiceStatus;
  status_label: string;
  document_type: "invoice" | "credit_note" | null;
  problems: EinvoiceProblem[];
  delivery_detail: string | null;
  target: EinvoiceMode | null;
  recipient: string | null;
  sent_at: string | null;
  delivered_at: string | null;
  tested_at: string | null;
  history: EinvoiceHistoryEntry[];
}

export interface EinvoiceList {
  mode: EinvoiceMode;
  auto_send: boolean;
  provider: string;
  provider_ready: boolean;
  provider_detail: string | null;
  rows: EinvoiceRow[];
  counts: Partial<Record<EinvoiceStatus, number>>;
}

export interface EinvoiceReceiver {
  key: string;
  name: string;
  peppol_id: string | null;
  test_peppol_id: string | null;
  legal_id: string | null;
  legal_id_scheme: string | null;
}

export interface EinvoiceSettings {
  mode: EinvoiceMode;
  auto_send: boolean;
  since: string;
  receivers: EinvoiceReceiver[];
  provider: string;
  provider_ready: boolean;
  provider_detail: string | null;
}

export interface EinvoiceSendResult {
  sent: number;
  failed: { id: number; invoice_number: string; reason: string }[];
  mode: EinvoiceMode;
}

export const einvoiceKeys = {
  all: ["client-einvoices"] as const,
  clients: ["client-einvoices", "clients"] as const,
  list: (clientId: number, month: string) => ["client-einvoices", "list", clientId, month] as const,
  settings: ["client-einvoices", "settings"] as const,
};

export function useEinvoiceClients() {
  return useQuery({
    queryKey: einvoiceKeys.clients,
    queryFn: async () => (await api.get<{ client_ids: number[] }>(`${BASE}/clients`)).data,
    staleTime: 60_000,
  });
}

export function useEinvoices(clientId: number, month: string) {
  return useQuery({
    queryKey: einvoiceKeys.list(clientId, month),
    queryFn: async () => (await api.get<EinvoiceList>(BASE, { params: { client_id: clientId, month } })).data,
  });
}

export function useEinvoiceSettings() {
  return useQuery({
    queryKey: einvoiceKeys.settings,
    queryFn: async () => (await api.get<EinvoiceSettings>(`${BASE}/settings`)).data,
  });
}

export function useSendEinvoices() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (ids: number[]) => (await api.post<EinvoiceSendResult>(`${BASE}/send`, { ids })).data,
    onSettled: () => queryClient.invalidateQueries({ queryKey: einvoiceKeys.all }),
  });
}

export function useRefreshEinvoices() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      (await api.post<{ created: number; checked: number; refreshed: number }>(`${BASE}/refresh`)).data,
    onSettled: () => queryClient.invalidateQueries({ queryKey: einvoiceKeys.all }),
  });
}

export function useSaveEinvoiceSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (patch: Partial<Pick<EinvoiceSettings, "mode" | "auto_send" | "since" | "receivers">>) =>
      (await api.put<EinvoiceSettings>(`${BASE}/settings`, patch)).data,
    onSettled: () => queryClient.invalidateQueries({ queryKey: einvoiceKeys.all }),
  });
}

export async function fetchEinvoiceUbl(id: number): Promise<Blob> {
  return (await api.get<Blob>(`${BASE}/${id}/ubl`, { responseType: "blob" })).data;
}
