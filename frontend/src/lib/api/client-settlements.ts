// Rozliczenia klientów (roadmapa `docs/rozliczenia-klientow-roadmapa.md`, E1.3):
// miesiąc klienta, karta osoby, przyjęcie RCP i reguły klienta.
//
// Lustro `backend/app/api/client_settlements.py` (`/api/finance/settlements…`,
// moduł Finanse; kwoty i marża tylko przy `can_read_client_finance`, inaczej `null`).
// Kwoty i MD przychodzą jako tekst dziesiętny z kropką.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

const BASE = "/api/finance/settlements";

/** Stan RCP osoby w miesiącu. `missing` — nic nie wpłynęło. */
export type SettlementStatus =
  | "missing"
  | "checking"
  | "ok"
  | "warnings"
  | "needs_fix"
  | "no_md"
  | "accepted";
/** Faktura kontraktora z KSeF (E4); `nip_check` — NIP z faktury czeka na Finanse (E4.0). */
export type ContractorInvoiceState = "none" | "can_issue" | "in_ksef" | "differs" | "nip_check";
export type ClientInvoiceState = "waiting" | "ready" | "issued";
export type CheckState = "ok" | "warn" | "fail" | "none";
export type RuleLevel = "block" | "warn" | "off";
export type SettlementFilter = "todo" | "missing" | "needs_fix" | "accepted" | "all";

export interface SettlementClient {
  client_id: number;
  name: string;
  active_contracts: number;
  rules_set: boolean;
  todo: number;
}

export interface SettlementRow {
  contract_id: number;
  settlement_id: number | null;
  person: string;
  order_number: string | null;
  status: SettlementStatus;
  issues: string | null;
  md_regular: string | null;
  md_extra: string | null;
  md_charged: string | null;
  md_remaining_after: string | null;
  amount_cost: string | null;
  amount_revenue: string | null;
  margin: string | null;
  margin_pct: string | null;
  contractor_invoice: ContractorInvoiceState;
  client_invoice: ClientInvoiceState;
}

export interface SettlementMonth {
  client_id: number;
  client_name: string;
  month: string;
  can_see_amounts: boolean;
  counts: Record<SettlementFilter, number>;
  /** Ile `ok` przyjmie „Przyjmij bez uwag”. */
  batch_ready: number;
  rows: SettlementRow[];
}

export interface SettlementCheck {
  state: CheckState;
  title: string;
  detail: string | null;
}

export interface SettlementCheckGroup {
  title: string;
  checks: SettlementCheck[];
}

export interface SettlementLine {
  label: string;
  md: string;
  multiplier: string;
  rate: string | null;
  net: string | null;
}

export interface SettlementDocument {
  id: number;
  kind: "report" | "invoice";
  file_name: string | null;
  channel: "portal" | "mailbox";
  mime: string;
  received_at: string;
}

/** `estimate` — plan miesiąca przysłany przed jego końcem (E5.3). */
export type SettlementKind = "actual" | "estimate";

export interface SettlementDetail {
  contract_id: number;
  settlement_id: number | null;
  kind?: SettlementKind;
  /** Plan tego miesiąca, gdy karta pokazuje RCP faktyczne. */
  estimate?: { status: SettlementStatus; md_regular: string | null; md_charged: string | null } | null;
  person: string;
  client_name: string;
  month: string;
  order_number: string | null;
  contract_number: string | null;
  status: SettlementStatus;
  /** Powód odesłania do poprawy (stan `needs_fix`). */
  fix_reason: string | null;
  documents: SettlementDocument[];
  /** MD z RCP: w E1 wpisują je Finanse, od E2 odczyt pliku. */
  md_regular: string | null;
  md_extra: string | null;
  /** `rcp` — odczyt pliku (E2), `manual` — wpis Finansów (wygrywa z odczytem). */
  md_source: "rcp" | "manual" | null;
  lines: SettlementLine[];
  total_md: string | null;
  total_net: string | null;
  checks: SettlementCheckGroup[];
  order: { md_total: string | null; md_charged: string | null; md_remaining_after: string | null } | null;
  contractor_invoice?: ContractorInvoiceBlock;
}

export interface ContractorInvoice {
  id: number;
  ksef_number: string;
  invoice_number: string | null;
  issue_date: string | null;
  acquired_at: string | null;
  seller_name: string | null;
  seller_nip: string;
  /** `known` — NIP z kontraktu, `suggested` — do zatwierdzenia, `confirmed` — zatwierdzony. */
  nip_state: "known" | "suggested" | "confirmed";
  net_amount: string | null;
  gross_amount: string | null;
  due_date: string | null;
}

export interface ContractorInvoiceBlock {
  state: ContractorInvoiceState;
  invoices: ContractorInvoice[];
  checks: SettlementCheck[];
}

export interface SettlementRule {
  key: string;
  name: string;
  level: RuleLevel;
  /** Wartości parametrów reguły; opis pól w `param_fields`. */
  params: Record<string, string>;
  param_fields: { key: string; label: string; suffix?: string | null }[];
  hint: string | null;
}

export interface SettlementRuleSection {
  key: string;
  title: string;
  rules: SettlementRule[];
}

export interface ClientRules {
  client_id: number;
  client_name: string;
  effective_from: string | null;
  sections: SettlementRuleSection[];
}

export const settlementKeys = {
  module: ["client-settlements", "module"] as const,
  clients: ["client-settlements", "clients"] as const,
  month: (clientId: number, month: string) => ["client-settlements", "month", clientId, month] as const,
  detail: (contractId: number, month: string, kind: SettlementKind = "actual") =>
    ["client-settlements", "detail", contractId, month, kind] as const,
  clientInvoice: (clientId: number, month: string) => ["client-settlements", "client-invoice", clientId, month] as const,
  estimates: (clientId: number, month: string) => ["client-settlements", "estimates", clientId, month] as const,
  clientDocuments: (clientId: number, month: string) =>
    ["client-settlements", "client-documents", clientId, month] as const,
  rules: (clientId: number, month: string) => ["client-settlements", "rules", clientId, month] as const,
};

export function useSettlementsModule(enabled = true) {
  return useQuery({
    queryKey: settlementKeys.module,
    queryFn: async () => (await api.get<{ enabled: boolean; open: boolean }>(`${BASE}/module`)).data,
    staleTime: 5 * 60 * 1000,
    enabled,
  });
}

export function useSettlementClients() {
  return useQuery({
    queryKey: settlementKeys.clients,
    queryFn: async () => (await api.get<SettlementClient[]>(`${BASE}/clients`)).data,
  });
}

export function useSettlementMonth(clientId: number | null, month: string) {
  return useQuery({
    queryKey: settlementKeys.month(clientId ?? 0, month),
    queryFn: async () =>
      (await api.get<SettlementMonth>(BASE, { params: { client_id: clientId, month } })).data,
    enabled: clientId != null,
  });
}

export function useSettlementDetail(contractId: number | null, month: string, kind: SettlementKind = "actual") {
  return useQuery({
    queryKey: settlementKeys.detail(contractId ?? 0, month, kind),
    queryFn: async () =>
      (await api.get<SettlementDetail>(`${BASE}/contract/${contractId}`, { params: { month, kind } })).data,
    enabled: contractId != null,
  });
}

/** Pozycja faktury do klienta jak w KSeF (E5.1); `correction` — różnica estymacji. */
export interface ClientInvoicePosition {
  name: string;
  unit: string;
  quantity: string;
  unit_price: string | null;
  net: string | null;
  kind: "base" | "overtime" | "onboarding" | "correction";
  /** Waluta faktury klienta (E6.2): stawka klienta z linii zamówienia, np. EUR. */
  currency: string;
}

export interface ClientInvoiceRow {
  contract_id: number;
  person: string;
  order_number: string | null;
  kind: SettlementKind | null;
  state: ClientInvoiceState;
  positions: ClientInvoicePosition[];
  /** Waluta `net`; koszt i marża są zawsze w zł. */
  currency: string;
  net: string | null;
  cost: string | null;
  margin: string | null;
  margin_pct: string | null;
  /** Nazwa pozycji z poprzedniej faktury do klienta (bez tego — nazwa zastępcza). */
  template: boolean;
  ksef_number: string | null;
  invoice_number: string | null;
}

export interface ClientInvoiceMonth {
  client_id: number;
  client_name: string;
  month: string;
  can_see_amounts: boolean;
  rows: ClientInvoiceRow[];
}

export interface EstimateRow {
  contract_id: number;
  person: string;
  order_number: string | null;
  previous_status: SettlementStatus;
  previous_md: string | null;
  remaining_after_previous: string | null;
  plan_status: SettlementStatus;
  plan_md: string | null;
  over_pool: string | null;
  /** Dwie osobne faktury do klienta: za poprzedni miesiąc i za plan (10.11). */
  previous_invoice: string | null;
  plan_invoice: string | null;
  /** Waluta obu faktur do klienta. */
  currency: string;
}

export interface EstimatesMonth {
  client_id: number;
  client_name: string;
  month: string;
  previous_month: string;
  enabled: boolean;
  can_see_amounts: boolean;
  rows: EstimateRow[];
}

export function useClientInvoiceMonth(clientId: number | null, month: string) {
  return useQuery({
    queryKey: settlementKeys.clientInvoice(clientId ?? 0, month),
    queryFn: async () =>
      (await api.get<ClientInvoiceMonth>(`${BASE}/client-invoice`, { params: { client_id: clientId, month } })).data,
    enabled: clientId != null,
  });
}

export function useEstimates(clientId: number | null, month: string) {
  return useQuery({
    queryKey: settlementKeys.estimates(clientId ?? 0, month),
    queryFn: async () =>
      (await api.get<EstimatesMonth>(`${BASE}/estimates`, { params: { client_id: clientId, month } })).data,
    enabled: clientId != null,
  });
}

/** Zip z RCP i mailami przyjętych rozliczeń miesiąca (E5.2): jednej osoby
 * albo hurtem tylko tych z wystawioną fakturą (nazwa z numeru KSeF). */
export async function fetchAttachmentsZip(
  clientId: number,
  month: string,
  options: { contractId?: number; issuedOnly?: boolean } = {},
): Promise<Blob> {
  return (
    await api.get<Blob>(`${BASE}/client-invoice/attachments`, {
      params: {
        client_id: clientId,
        month,
        contract_id: options.contractId,
        issued_only: options.issuedOnly || undefined,
      },
      responseType: "blob",
    })
  ).data;
}

/** Potwierdzenie usług dla klienta na projekt (E6.2, reguła `cl.client_document`). */
export interface ClientDocumentProject {
  project: string;
  people: number;
  accepted: number;
  hours: string;
  md: string;
  order_numbers: string[];
  tasks: number;
  /** Blok kosztów do maila do automatu klienta (reguła `cl.cost_mail_block`); `null` = reguła wyłączona. */
  esp: ClientDocumentCostBlock | null;
}

export interface ClientDocumentCostBlock {
  /** Wszystkie osoby projektu przyjęte, jest numer zamówienia i stawka klienta. */
  ready: boolean;
  /** MD z pozycji faktury do klienta (z limitem puli), nie z godzin Time Sheet. */
  md: string;
  currency: string | null;
  /** Tylko dla kont z dostępem do kwot i gotowego bloku. */
  cost: string | null;
  text: string | null;
}

export interface ClientDocumentsMonth {
  client_id: number;
  month: string;
  /** Reguła obejmuje miesiąc i dokument jest na projekt. */
  enabled: boolean;
  kind: string;
  /** `FORECAST` — z planu miesiąca (estymacja), `ACTUAL` — z Time Sheet. */
  stage: "ACTUAL" | "FORECAST" | null;
  can_see_amounts: boolean;
  projects: ClientDocumentProject[];
  skipped: { person: string; reason: string }[];
}

export function useClientDocuments(clientId: number | null, month: string) {
  return useQuery({
    queryKey: settlementKeys.clientDocuments(clientId ?? 0, month),
    queryFn: async () =>
      (await api.get<ClientDocumentsMonth>(`${BASE}/client-documents`, { params: { client_id: clientId, month } })).data,
    enabled: clientId != null,
  });
}

export async function fetchClientDocument(clientId: number, month: string, project: string): Promise<Blob> {
  return (
    await api.get<Blob>(`${BASE}/client-documents/file`, {
      params: { client_id: clientId, month, project },
      responseType: "blob",
    })
  ).data;
}

/** Plik RCP albo maila z karty osoby (do sprawdzenia przed przyjęciem). */
export async function fetchSettlementDocument(contractId: number, documentId: number): Promise<Blob> {
  return (await api.get<Blob>(`${BASE}/contract/${contractId}/documents/${documentId}`, { responseType: "blob" })).data;
}

export function useClientRules(clientId: number | null, month: string) {
  return useQuery({
    queryKey: settlementKeys.rules(clientId ?? 0, month),
    queryFn: async () =>
      (await api.get<ClientRules>(`${BASE}/rules/${clientId}`, { params: { month } })).data,
    enabled: clientId != null,
  });
}

function useInvalidateSettlements() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["client-settlements"] });
}

export function useAcceptSettlement(month: string, kind: SettlementKind = "actual") {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async (contractId: number) =>
      (await api.post<SettlementDetail>(`${BASE}/contract/${contractId}/accept`, null, { params: { month, kind } })).data,
    onSuccess: invalidate,
  });
}

export function useSetSettlementMd(month: string, kind: SettlementKind = "actual") {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async ({ contractId, mdRegular, mdExtra }: { contractId: number; mdRegular: string; mdExtra: string | null }) =>
      (
        await api.put<SettlementDetail>(
          `${BASE}/contract/${contractId}/md`,
          { md_regular: mdRegular, md_extra: mdExtra },
          { params: { month, kind } },
        )
      ).data,
    onSuccess: invalidate,
  });
}

export function useNeedsFixSettlement(month: string, kind: SettlementKind = "actual") {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async ({ contractId, reason }: { contractId: number; reason: string }) =>
      (
        await api.post<SettlementDetail>(`${BASE}/contract/${contractId}/needs-fix`, { reason }, { params: { month, kind } })
      ).data,
    onSuccess: invalidate,
  });
}

/** Podpowiedź NIP-u z faktury w KSeF (E4.0): zatwierdzenie zapisuje NIP osobie. */
export function useNipDecision() {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async ({ invoiceId, approve }: { invoiceId: number; approve: boolean }) =>
      (await api.post(`${BASE}/contractor-invoices/${invoiceId}/${approve ? "approve-nip" : "reject-nip"}`)).data,
    onSuccess: invalidate,
  });
}

export function useAcceptBatch() {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async ({ clientId, month, kind = "actual" }: { clientId: number; month: string; kind?: SettlementKind }) =>
      (await api.post<{ accepted: number }>(`${BASE}/accept-batch`, { client_id: clientId, month, kind })).data,
    onSuccess: invalidate,
  });
}

export function useSaveClientRules(clientId: number) {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async (body: {
      effective_from: string;
      rules: { key: string; level: RuleLevel; params: Record<string, string> }[];
    }) => (await api.put<ClientRules>(`${BASE}/rules/${clientId}`, body)).data,
    onSuccess: invalidate,
  });
}

export function useCopyClientRules(clientId: number) {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async (sourceClientId: number) =>
      (await api.post<ClientRules>(`${BASE}/rules/${clientId}/copy-from/${sourceClientId}`)).data,
    onSuccess: invalidate,
  });
}
