// Rozliczenia klientów (roadmapa `docs/rozliczenia-klientow-roadmapa.md`, E1.3):
// miesiąc klienta, karta osoby, przyjęcie RCP i reguły klienta.
//
// Lustro `backend/app/api/client_settlements.py` (`/api/finance/settlements…`,
// moduł Finanse; kwoty i marża tylko przy `can_read_client_finance`, inaczej `null`).
// Kwoty i MD przychodzą jako tekst dziesiętny z kropką.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { PanelState } from "@/lib/api/consultant-panel";
import type {
  PortalMe,
  PortalMonth,
  PortalSettlement,
  PortalTodoItem,
} from "@/lib/api/consultant-portal";

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
/** Faktura kontraktora z KSeF (E4); `nip_check` — NIP z faktury czeka na Finanse (E4.0);
 * `extra_pending` — różnica faktury to zgłoszony, niezatwierdzony dodatek. */
export type ContractorInvoiceState =
  "none" | "can_issue" | "in_ksef" | "differs" | "nip_check" | "extra_pending";
/** `awaiting_signature` — czeka na podpis klienta: KEŚU (E6.3), protokół albo arkusze (E6.1, E6.2); reguła `cl.after_signed_document`. */
export type ClientInvoiceState =
  "waiting" | "ready" | "issued" | "awaiting_signature" | "awaiting_client" | "awaiting_t4t";
/** Akceptacja dowodu pracy przez klienta po zbiorczej wysyłce (E6.5, Bank Pocztowy). */
export type ClientAcceptanceState = "none" | "to_send" | "sent" | "accepted";

export interface ClientAcceptanceSummary {
  state: ClientAcceptanceState;
  sent_at: string | null;
  accepted_at: string | null;
  /** Pierwsza linia odpowiedzi klienta, gdy akceptacja przyszła mailem. */
  reply: string | null;
  source: "mail" | "manual" | null;
}
/** Stan KEŚU osoby w miesiącu (E6.3, klient z Jirą). */
export type KesuState = "to_company" | "awaiting_client" | "signed";
export type CheckState = "ok" | "warn" | "fail" | "none";
export type RuleLevel = "block" | "warn" | "off";
export type SettlementFilter =
  "todo" | "missing" | "needs_fix" | "accepted" | "all";

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
  /** „fail” — reguła blokuje przyjęcie; „warn” — uwaga do przyjęcia na karcie osoby. */
  issue_level?: "fail" | "warn" | null;
  /** Przyjęte mimo uwag albo błędów — rozstrzygnął człowiek, nie automat. */
  accepted_issue?: boolean;
  /** `rcp` — MD odczytane z pliku, `manual` — wpisane przez Finanse. */
  md_source?: "rcp" | "manual" | null;
  md_regular: string | null;
  md_extra: string | null;
  md_charged: string | null;
  md_remaining_after: string | null;
  amount_cost: string | null;
  amount_revenue: string | null;
  /** Przyjęte koszty integracji miesiąca (E5.1) — już odjęte od marży. */
  integration_cost?: string | null;
  margin: string | null;
  margin_pct: string | null;
  contractor_invoice: ContractorInvoiceState;
  client_invoice: ClientInvoiceState;
  /** KEŚU z Jiry (E6.3): stan, opiekun i czas, bez kwot. */
  kesu?: KesuSummary | null;
  /** Dodatki zgłoszone, a jeszcze niezatwierdzone przez Finanse. */
  extras_pending?: number;
  /** Akceptacja klienta po wysyłce KCP (E6.5); `null`, gdy klient nie ma tej reguły. */
  client_acceptance?: ClientAcceptanceSummary | null;
  /** Przyjęte przez automat „Przyjmuj RCP bez uwag automatycznie”. */
  accepted_auto?: boolean;
}

/** Automat przyjęcia „Bez uwag” w miesiącu klienta; `null`, gdy reguła wyłączona. */
export interface AutoAcceptInfo {
  /** Ile RCP „Bez uwag” przyjmie automat (bez odesłanych „Do poprawy”). */
  count: number;
  /** Od którego dnia roboczego następnego miesiąca. */
  workday: number;
  /** Data (RRRR-MM-DD), od której automat bierze ten miesiąc. */
  from: string;
}

export interface KesuSummary {
  state: KesuState;
  state_label: string;
  approver: string | null;
  accepted_at: string | null;
  hours: string | null;
  days: number | null;
}

export interface KesuPayment {
  state: CheckState;
  title: string;
  detail: string | null;
  can_pay: boolean;
  on_mail: boolean;
  /** Reguła pozwala zapłacić po mailowej akceptacji, gdy podpisujący jest nieobecny. */
  can_use_mail: boolean;
}

/** KEŚU na karcie osoby. Kwoty i stawki tylko z dostępem do kwot (inaczej `null`). */
export interface KesuBlock extends KesuSummary {
  approver_email: string | null;
  md_hours: string;
  rate_md: string | null;
  rate_contract: string | null;
  rate_order: string | null;
  fee_gross: string | null;
  extra_costs: string | null;
  total_gross: string | null;
  rate_differs: boolean;
  mail: {
    to: string | null;
    to_name: string | null;
    subject: string;
    body: string;
  };
  payment: KesuPayment | null;
  invoice_waits: boolean;
  package_ready: boolean;
}

export interface SettlementMonth {
  client_id: number;
  client_name: string;
  month: string;
  can_see_amounts: boolean;
  counts: Record<SettlementFilter, number>;
  /** Ile `ok` przyjmie „Przyjmij bez uwag”. */
  batch_ready: number;
  auto_accept?: AutoAcceptInfo | null;
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
  estimate?: {
    status: SettlementStatus;
    md_regular: string | null;
    md_charged: string | null;
  } | null;
  person: string;
  client_name: string;
  month: string;
  order_number: string | null;
  contract_number: string | null;
  status: SettlementStatus;
  /** Powód odesłania do poprawy (stan `needs_fix`). */
  fix_reason: string | null;
  accepted_at?: string | null;
  /** Przyjęte przez automat „Przyjmuj RCP bez uwag automatycznie”. */
  accepted_auto?: boolean;
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
  order: {
    md_total: string | null;
    md_charged: string | null;
    md_remaining_after: string | null;
  } | null;
  contractor_invoice?: ContractorInvoiceBlock;
  kesu?: KesuBlock | null;
  /** KCP w PDF do pobrania (E6.5): od konsultanta albo złożona z eksportu Redmine. */
  kcp_pdf?: boolean;
  extras?: SettlementExtrasBlock;
}

/** Dodatek do rozliczenia kontraktora: polecenie, weryfikacja techniczna, szkolenie, delegacja. */
export type SettlementExtraKind = "referral" | "tech_check" | "training" | "travel" | "integration" | "other";
export type SettlementExtraStatus = "pending" | "approved" | "rejected";

export interface SettlementExtraDocument {
  id: number;
  file_name: string | null;
  mime: string;
  channel: "portal" | "staff";
  received_at: string | null;
}

export interface SettlementExtra {
  id: number;
  contract_id: number;
  month: string;
  kind: SettlementExtraKind;
  kind_label: string;
  /** Netto; `null` bez dostępu do kwot. */
  amount: string | null;
  description: string;
  status: SettlementExtraStatus;
  status_label: string;
  source: "back_office" | "finance" | "portal";
  source_label: string;
  reported_by: string | null;
  decided_by: string | null;
  decided_at: string | null;
  /** Powód odrzucenia. */
  decision_note: string | null;
  bill_to_client: boolean;
  bo_card_id: number | null;
  /** `false` dla kosztów integracji (ścieżka DL-a, nie faktura kontraktora). */
  counts_on_invoice: boolean;
  created_at: string | null;
  documents: SettlementExtraDocument[];
  /** Tylko w widoku karty back office'u. */
  person?: string | null;
}

export interface SettlementExtrasBlock {
  items: SettlementExtra[];
  approved_total: string | null;
  pending_total: string | null;
  pending_count: number;
  kinds: { key: SettlementExtraKind; label: string }[];
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
  /** Faktura korygująca (kwoty to różnice). */
  is_correction?: boolean;
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
  /** Reguła „włącz / wyłącz”: przełącznik zamiast poziomu (`block` = włączona). */
  switch?: boolean;
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

/** Karta „Start rozliczeń” (admin): przełączniki i to, czego brakuje do startu. */
export interface SettlementsStart {
  module_enabled: boolean;
  portal_state: PanelState;
  back_office: boolean;
  mailbox: {
    configured: boolean;
    last_run_at: string | null;
    last_status: string | null;
    last_error: string | null;
  };
  rule_clients: {
    client_id: number;
    name: string;
    effective_from: string;
    md_charged_on_accept: boolean;
  }[];
  active_panels: number;
}

/** Panel oczami konsultanta (tylko odczyt), te same dane co ekrany panelu. */
export interface PanelPreview {
  activated: boolean;
  me: PortalMe;
  todo: { items: PortalTodoItem[] };
  settlement: PortalSettlement;
  finance: { months: PortalMonth[] };
}

/** Pięć kroków miesiąca (`month_close.stage_counts`): każda osoba raz w każdym kroku. */
export interface MonthCloseStages {
  people: number;
  /** `md_auto` — MD odczytał automat z pliku, `md_manual` — wpisały Finanse. */
  report: { in: number; missing: number; md_auto: number; md_manual: number };
  check: {
    clean: number;
    /** Część `clean`: automat odczytał plik i reguły nie miały uwag. */
    auto_clean: number;
    /** Przyjęte mimo uwag albo błędów (rozstrzygnął człowiek). */
    resolved: number;
    warn: number;
    fail: number;
    returned: number;
    unread: number;
    no_md: number;
    missing: number;
  };
  accept: { done: number; auto: number; ready: number };
  /** `waiting` — RCP przyjęte, faktury kontraktora jeszcze nie ma (ruch konsultanta). */
  contractor_invoice: { match: number; differs: number; nip: number; can_issue: number; none: number; waiting: number };
  client_invoice: {
    issued: number;
    ready: number;
    waiting_client: number;
    waiting: number;
    /** Faktura sprzedaży w KSeF, choć RCP w NEXUS-ie nieprzyjęte. */
    issued_early: number;
  };
  missing_order: number;
}

/** Rodzaj sprawy w kolejce: błąd blokuje przyjęcie, uwagę Finanse mogą przyjąć. */
export type MonthCloseReasonLevel = "fail" | "warn" | "unread" | "order" | "returned" | "missing";

/** „Przebieg miesiąca”: wiersz klienta (GET /overview). */
export interface MonthCloseClient {
  client_id: number;
  name: string;
  people: number;
  clean: number;
  accepted: number;
  decide: number;
  unread: number;
  missing: number;
  contractor_in_ksef: number;
  client_invoice_issued: number;
  client_invoice_ready: number;
  revenue_ready: string | null;
  top_reason: string | null;
  /** Klient rozliczany z raportu klienta (T4T) — bez kolejki osób. */
  client_report: { all: number; ok: number; differs: number; unmatched: number; no_invoice: number } | null;
  /** Reguła `order.auto_accept_clean`: ile „Bez uwag” przyjmie automat i od kiedy. */
  auto_accept?: AutoAcceptInfo | null;
  stages?: MonthCloseStages;
}

/** Osoba na liście dla księgowej (tylko z uprawnieniem do kwot). */
export interface MonthCloseClosingRow {
  client_id: number;
  client: string;
  contract_id: number;
  person: string;
  md: string | null;
  cost: string | null;
}

/** Trzy pytania księgowej na zamknięcie miesiąca. */
export interface MonthCloseClosing {
  ksef_not_accepted: number;
  reserve_count: number;
  reserve_total: string | null;
  reserve_without_cost: number;
  sales_waiting: number;
  rows: Record<"ksef_not_accepted" | "reserve" | "sales_waiting", MonthCloseClosingRow[]> | null;
}

export interface MonthCloseReason {
  /** Klucz reguły albo `missing` / `no_md`. */
  key: string;
  title: string;
  level?: MonthCloseReasonLevel;
  count: number;
  clients: { client_id: number; name: string; count: number }[];
  people: { contract_id: number; person: string; client_id: number }[];
}

export interface MonthCloseOverview {
  month: string;
  can_see_amounts: boolean;
  totals: {
    people: number;
    clean: number;
    accepted: number;
    decide: number;
    unread: number;
    missing: number;
    contractor_in_ksef: number;
    client_invoice_issued: number;
  };
  stages?: MonthCloseStages;
  clients: MonthCloseClient[];
  reasons: MonthCloseReason[];
  closing?: MonthCloseClosing;
}

/**
 * Biuro — nasi ludzie na B2B (klientem jesteśmy my, faktury do klienta nie ma).
 * `GET /api/finance/settlements/team?month=` (`team_month.py`): ewidencja czasu,
 * faktura z KSeF z Płac (tylko po NIP-ie z „Danych do rozliczeń”) i zapłata.
 * Bez kwot — kwoty biura zostają w Płacach (decyzja Artura z 24.11.2026).
 */
export interface TeamMonthPerson {
  user_id: number;
  person: string;
  /** Ewidencja czasu za miesiąc. */
  timesheet: "approved" | "submitted" | "draft" | "returned" | "missing";
  timesheet_on: string | null;
  /** Faktura osoby w KSeF za miesiąc; `no_nip` — brak NIP-u w „Danych do rozliczeń”. */
  invoice: "in_ksef" | "differs" | "missing" | "no_nip";
  invoice_on: string | null;
  paid: boolean;
  paid_on: string | null;
}

export interface TeamMonth {
  month: string;
  people: TeamMonthPerson[];
}

export const settlementKeys = {
  module: ["client-settlements", "module"] as const,
  start: ["client-settlements", "start"] as const,
  preview: (contractId: number) =>
    ["client-settlements", "preview", contractId] as const,
  clients: ["client-settlements", "clients"] as const,
  contractNipReview: ["client-settlements", "contract-nip-review"] as const,
  overview: (month: string) => ["client-settlements", "overview", month] as const,
  month: (clientId: number, month: string) =>
    ["client-settlements", "month", clientId, month] as const,
  detail: (
    contractId: number,
    month: string,
    kind: SettlementKind = "actual",
  ) => ["client-settlements", "detail", contractId, month, kind] as const,
  clientInvoice: (clientId: number, month: string) =>
    ["client-settlements", "client-invoice", clientId, month] as const,
  estimates: (clientId: number, month: string) =>
    ["client-settlements", "estimates", clientId, month] as const,
  clientDocuments: (clientId: number, month: string) =>
    ["client-settlements", "client-documents", clientId, month] as const,
  clientAcceptance: (clientId: number, month: string) =>
    ["client-settlements", "client-acceptance", clientId, month] as const,
  rules: (clientId: number, month: string) =>
    ["client-settlements", "rules", clientId, month] as const,
  integration: (contractId: number, month: string) =>
    ["client-settlements", "integration", contractId, month] as const,
  delivery: (clientId: number, month: string) =>
    ["client-settlements", "delivery", clientId, month] as const,
};

export function useSettlementsModule(enabled = true) {
  return useQuery({
    queryKey: settlementKeys.module,
    queryFn: async () =>
      (await api.get<{ enabled: boolean; open: boolean }>(`${BASE}/module`))
        .data,
    staleTime: 5 * 60 * 1000,
    enabled,
  });
}

export function useSettlementsStart(enabled: boolean) {
  return useQuery({
    queryKey: settlementKeys.start,
    queryFn: async () =>
      (await api.get<SettlementsStart>(`${BASE}/start`)).data,
    enabled,
    retry: false,
  });
}

export function useSetSettlementsModule() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (enabled: boolean) =>
      (
        await api.put<{ enabled: boolean; open: boolean }>(`${BASE}/module`, {
          enabled,
        })
      ).data,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: settlementKeys.module });
      void client.invalidateQueries({ queryKey: settlementKeys.start });
    },
  });
}

export function usePanelPreview(contractId: number | null) {
  return useQuery({
    queryKey: settlementKeys.preview(contractId ?? 0),
    queryFn: async () =>
      (
        await api.get<PanelPreview>(
          `${BASE}/contract/${contractId}/panel-preview`,
        )
      ).data,
    enabled: contractId != null,
    retry: false,
  });
}

/** Umowa B2B, której `partner_nip` wskazuje inną firmę (audyt 25.11.2026). */
export interface ContractNipReviewItem {
  contract_id: number;
  client_id: number | null;
  client_name: string | null;
  person: string | null;
  partner_nip: string;
  partner_name: string | null;
  partner_legal_name: string | null;
  generated_contract_id: number;
  sellers: { name: string; invoices: number }[];
  invoices: number;
  reasons: { key: "partner_other_person" | "seller_without_person"; label: string }[];
}

export function useContractNipReview() {
  return useQuery({
    queryKey: settlementKeys.contractNipReview,
    queryFn: async () =>
      (await api.get<{ items: ContractNipReviewItem[] }>(`${BASE}/contract-nip-review`)).data,
  });
}

export function useSettlementClients() {
  return useQuery({
    queryKey: settlementKeys.clients,
    queryFn: async () =>
      (await api.get<SettlementClient[]>(`${BASE}/clients`)).data,
  });
}

export function useMonthCloseOverview(month: string) {
  return useQuery({
    queryKey: settlementKeys.overview(month),
    queryFn: async () =>
      (await api.get<MonthCloseOverview>(`${BASE}/overview`, { params: { month } })).data,
  });
}

/** Biuro w miesiącu: stany bez kwot. */
export function useTeamMonth(month: string) {
  return useQuery({
    queryKey: ["client-settlements", "team", month] as const,
    queryFn: async () => (await api.get<TeamMonth>(`${BASE}/team`, { params: { month } })).data,
    retry: false,
  });
}

export function useSettlementMonth(clientId: number | null, month: string) {
  return useQuery({
    queryKey: settlementKeys.month(clientId ?? 0, month),
    queryFn: async () =>
      (
        await api.get<SettlementMonth>(BASE, {
          params: { client_id: clientId, month },
        })
      ).data,
    enabled: clientId != null,
  });
}

export function useSettlementDetail(
  contractId: number | null,
  month: string,
  kind: SettlementKind = "actual",
) {
  return useQuery({
    queryKey: settlementKeys.detail(contractId ?? 0, month, kind),
    queryFn: async () =>
      (
        await api.get<SettlementDetail>(`${BASE}/contract/${contractId}`, {
          params: { month, kind },
        })
      ).data,
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
  kind: "base" | "overtime" | "onboarding" | "correction" | "extra";
  /** Waluta faktury klienta (E6.2): stawka klienta z linii zamówienia, np. EUR. */
  currency: string;
}

/** Godziny osoby z ostatniej wersji raportu T4T (klient z `report.time_for_teams`). */
export interface ClientInvoiceT4t {
  approved: string;
  /** Status 0 i 1: czekają na akceptację managera. */
  pending: string;
  /** Godziny na pozycji: zatwierdzone albo z mailowej akceptacji managera. */
  billed: string;
  /** Godziny na wystawionej fakturze za miesiąc; `null` bez faktury. */
  invoiced: string | null;
  notes: string[];
}

export interface ClientInvoiceRow {
  contract_id: number;
  person: string;
  order_number: string | null;
  /** Linia zamówienia wiersza; przy podziale z maila klienta osoba ma wiersz na każde zamówienie. */
  order_id?: number | null;
  /** `time_report` — pozycja z raportu T4T, nie z RCP. */
  kind: SettlementKind | "time_report" | null;
  /** Dlaczego pozycja czeka (T4T: godziny niezatwierdzone w wersji z DD.MM). */
  hold_reason?: string | null;
  t4t?: ClientInvoiceT4t | null;
  state: ClientInvoiceState;
  positions: ClientInvoicePosition[];
  /** Waluta `net`; koszt i marża są zawsze w zł. */
  currency: string;
  net: string | null;
  cost: string | null;
  /** Przyjęte koszty integracji miesiąca (E5.1) — już odjęte od marży. */
  integration_cost?: string | null;
  margin: string | null;
  margin_pct: string | null;
  /** Nazwa pozycji z poprzedniej faktury do klienta (bez tego — nazwa zastępcza). */
  template: boolean;
  ksef_number: string | null;
  invoice_number: string | null;
  /** Dodatek do faktury klienta, który nie wszedł do pozycji (reguła wyłączona, inna waluta). */
  extras_note?: string | null;
}

export interface ClientInvoiceMonth {
  client_id: number;
  client_name: string;
  month: string;
  can_see_amounts: boolean;
  /** Faktura do klienta po podpisanym dokumencie (E6); `null` — nic nie wstrzymuje. */
  signature_hold?: { kind: "protocol" | "sheet"; label: string } | null;
  /** Ostatnia wersja raportu T4T, z której liczą się pozycje; `null` bez reguły T4T. */
  time_report?: { version_id: number | null; received_on: string | null; label: string } | null;
  /** Termin faktury (15. dnia następnego miesiąca) blisko albo minął, a osoby nie mają zatwierdzonych godzin. */
  deadline?: ClientInvoiceDeadline | null;
  rows: ClientInvoiceRow[];
}

export interface ClientInvoiceDeadline {
  date: string;
  days_left: number;
  overdue: boolean;
  missing: number;
  people: string[];
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
      (
        await api.get<ClientInvoiceMonth>(`${BASE}/client-invoice`, {
          params: { client_id: clientId, month },
        })
      ).data,
    enabled: clientId != null,
  });
}

export function useEstimates(clientId: number | null, month: string) {
  return useQuery({
    queryKey: settlementKeys.estimates(clientId ?? 0, month),
    queryFn: async () =>
      (
        await api.get<EstimatesMonth>(`${BASE}/estimates`, {
          params: { client_id: clientId, month },
        })
      ).data,
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

/** Protokół odbioru na wszystkie osoby miesiąca (E6.1, PKO). */
export interface ClientDocumentProtocol {
  people: number;
  accepted: number;
  /** Komplet: wszystkie osoby miesiąca przyjęte. Dopiero wtedy protokół i paczka. */
  ready: boolean;
  /** Adres paczki z reguły `cl.send_to`. */
  send_to: string | null;
  /** Klient podpisał protokół (rozpoznany po treści i dwóch podpisach). */
  signed: boolean;
  signed_by: string | null;
  missing_roles: string[];
  missing_orders: string[];
  waiting: { person: string; status: SettlementStatus }[];
  hours: string;
  /** Tylko dla kont z dostępem do kwot. */
  net: string | null;
  files: { person: string; timesheet: boolean }[];
}

/** Arkusze zbiorcze per osoba podpisująca u klienta (E6.2, Velo). */
export interface ClientDocumentSheets {
  signers: { signer: string; people: number; md: string; signed: number }[];
  rows: {
    contract_id: number;
    person: string;
    signer: string;
    md: string | null;
    status: SettlementStatus;
    signed: boolean;
    signed_by: string | null;
    signed_at: string | null;
    amount: string | null;
  }[];
  without_sheet: { person: string; status: SettlementStatus }[];
  all_signed: boolean;
  net: string | null;
}

export type ClientDocumentFileKind =
  "protocol" | "package" | "sheet" | "sheets" | "invoice_sheet";

export interface ClientDocumentsMonth {
  client_id: number;
  month: string;
  /** Reguła obejmuje miesiąc i dokument jest na projekt. */
  enabled: boolean;
  /** Brak = dokument na projekt (Service Delivery Confirmation). */
  layout?: "month" | "signer";
  protocol?: ClientDocumentProtocol;
  sheets?: ClientDocumentSheets;
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
      (
        await api.get<ClientDocumentsMonth>(`${BASE}/client-documents`, {
          params: { client_id: clientId, month },
        })
      ).data,
    enabled: clientId != null,
  });
}

export async function fetchClientDocument(
  clientId: number,
  month: string,
  project: string,
): Promise<Blob> {
  return (
    await api.get<Blob>(`${BASE}/client-documents/file`, {
      params: { client_id: clientId, month, project },
      responseType: "blob",
    })
  ).data;
}

/** Protokół, paczka i arkusze (E6.1, E6.2); `signer` tylko przy jednym arkuszu. */
export async function fetchClientDocumentFile(
  clientId: number,
  month: string,
  kind: ClientDocumentFileKind,
  signer?: string,
): Promise<Blob> {
  return (
    await api.get<Blob>(`${BASE}/client-documents/file`, {
      params: { client_id: clientId, month, kind, signer },
      responseType: "blob",
    })
  ).data;
}

/** Podpisany przez klienta protokół albo arkusz wgrany ręcznie (rozpoznanie po treści). */
export function useUploadSignedDocument(month: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("month", month);
      form.append("file", file);
      return (
        await api.post<{ document_id: number; recognized: boolean }>(
          `${BASE}/client-documents/signed`,
          form,
          {
            headers: { "Content-Type": "multipart/form-data" },
          },
        )
      ).data;
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["client-settlements"] }),
  });
}

/** Plik RCP albo maila z karty osoby (do sprawdzenia przed przyjęciem). */
export async function fetchSettlementDocument(
  contractId: number,
  documentId: number,
): Promise<Blob> {
  return (
    await api.get<Blob>(
      `${BASE}/contract/${contractId}/documents/${documentId}`,
      { responseType: "blob" },
    )
  ).data;
}

/** Paczka do podpisu spółki: KEŚU ze stawką i faktury kosztów w jednym PDF (E6.3). */
export async function fetchKesuPackage(
  contractId: number,
  month: string,
): Promise<Blob> {
  return (
    await api.get<Blob>(`${BASE}/contract/${contractId}/kesu/package`, {
      params: { month },
      responseType: "blob",
    })
  ).data;
}

export function useClientRules(clientId: number | null, month: string) {
  return useQuery({
    queryKey: settlementKeys.rules(clientId ?? 0, month),
    queryFn: async () =>
      (
        await api.get<ClientRules>(`${BASE}/rules/${clientId}`, {
          params: { month },
        })
      ).data,
    enabled: clientId != null,
  });
}

function useInvalidateSettlements() {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({ queryKey: ["client-settlements"] });
}

export function useAcceptSettlement(
  month: string,
  kind: SettlementKind = "actual",
) {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async (contractId: number) =>
      (
        await api.post<SettlementDetail>(
          `${BASE}/contract/${contractId}/accept`,
          null,
          { params: { month, kind } },
        )
      ).data,
    onSuccess: invalidate,
  });
}

export function useSetSettlementMd(
  month: string,
  kind: SettlementKind = "actual",
) {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async ({
      contractId,
      mdRegular,
      mdExtra,
    }: {
      contractId: number;
      mdRegular: string;
      mdExtra: string | null;
    }) =>
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

export function useNeedsFixSettlement(
  month: string,
  kind: SettlementKind = "actual",
) {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async ({
      contractId,
      reason,
    }: {
      contractId: number;
      reason: string;
    }) =>
      (
        await api.post<SettlementDetail>(
          `${BASE}/contract/${contractId}/needs-fix`,
          { reason },
          { params: { month, kind } },
        )
      ).data,
    onSuccess: invalidate,
  });
}

/** Podpisujący KEŚU nieobecny: zapłata konsultanta po mailowej akceptacji (E6.3). */
export function usePayOnMail(month: string) {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async (contractId: number) =>
      (
        await api.post<SettlementDetail>(
          `${BASE}/contract/${contractId}/pay-on-mail`,
          null,
          { params: { month } },
        )
      ).data,
    onSuccess: invalidate,
  });
}

/** Podpowiedź NIP-u z faktury w KSeF (E4.0): zatwierdzenie zapisuje NIP osobie. */
export function useNipDecision() {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async ({
      invoiceId,
      approve,
    }: {
      invoiceId: number;
      approve: boolean;
    }) =>
      (
        await api.post(
          `${BASE}/contractor-invoices/${invoiceId}/${approve ? "approve-nip" : "reject-nip"}`,
        )
      ).data,
    onSuccess: invalidate,
  });
}

export function useAcceptBatch() {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async ({
      clientId,
      month,
      kind = "actual",
    }: {
      clientId: number;
      month: string;
      kind?: SettlementKind;
    }) =>
      (
        await api.post<{ accepted: number }>(`${BASE}/accept-batch`, {
          client_id: clientId,
          month,
          kind,
        })
      ).data,
    onSuccess: invalidate,
  });
}

export function useSaveClientRules(clientId: number) {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async (body: {
      effective_from: string;
      rules: {
        key: string;
        level: RuleLevel;
        params: Record<string, string>;
      }[];
    }) => (await api.put<ClientRules>(`${BASE}/rules/${clientId}`, body)).data,
    onSuccess: invalidate,
  });
}

export function useCopyClientRules(clientId: number) {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async (sourceClientId: number) =>
      (
        await api.post<ClientRules>(
          `${BASE}/rules/${clientId}/copy-from/${sourceClientId}`,
        )
      ).data,
    onSuccess: invalidate,
  });
}

// ── Koszty integracji (E5.1, reguła `cl.integration_costs`) ─────────────────

export type IntegrationCostStatus = "pending" | "approved" | "rejected";

/** Licznik roku konsultanta: limit z reguły klienta (`null` = bez limitu). */
export interface IntegrationUsage {
  year: number;
  limit: string | null;
  approved: string;
  pending: string;
  remaining: string | null;
}

export interface IntegrationCost {
  id: number;
  contract_id: number;
  month: string;
  /** `null` bez dostępu do kwot klienta (`can_read_client_finance`). */
  amount: string | null;
  description: string;
  status: IntegrationCostStatus;
  decided_at: string | null;
  person?: string;
  usage?: IntegrationUsage | null;
}

export interface IntegrationCard {
  enabled: boolean;
  /** `null` bez dostępu do kwot. */
  usage: IntegrationUsage | null;
  items: IntegrationCost[];
}

export function useIntegrationCosts(contractId: number | null, month: string) {
  return useQuery({
    queryKey: settlementKeys.integration(contractId ?? 0, month),
    queryFn: async () =>
      (
        await api.get<IntegrationCard>(
          `${BASE}/contract/${contractId}/integration-costs`,
          { params: { month } },
        )
      ).data,
    enabled: contractId != null,
  });
}

export function useAddIntegrationCost(contractId: number, month: string) {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async (body: { amount: string; description: string }) =>
      (
        await api.post<IntegrationCard>(
          `${BASE}/contract/${contractId}/integration-costs`,
          body,
          { params: { month } },
        )
      ).data,
    onSuccess: invalidate,
  });
}

export function useWithdrawIntegrationCost(contractId: number, month: string) {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async (costId: number) =>
      (
        await api.delete<IntegrationCard>(
          `${BASE}/contract/${contractId}/integration-costs/${costId}`,
          { params: { month } },
        )
      ).data,
    onSuccess: invalidate,
  });
}

// ── Delivery Lead: marża i koszty integracji swoich klientów (E5.1) ────────
// `/api/my-clients/{id}/settlements` — sekcja Delivery; kwoty według
// `can_read_client_finance` (Finanse i DL u klienta z przypisania).

export interface DeliverySettlements extends ClientInvoiceMonth {
  integration: {
    enabled: boolean;
    limit: string | null;
    year: number;
    items: IntegrationCost[];
  };
  /** Konto jest Delivery Leadem tego klienta — tylko ono przyjmuje koszty. */
  can_decide: boolean;
}

const DELIVERY = (clientId: number) =>
  `/api/my-clients/${clientId}/settlements`;

export function useDeliverySettlements(
  clientId: number,
  month: string,
  enabled = true,
) {
  return useQuery({
    queryKey: settlementKeys.delivery(clientId, month),
    queryFn: async () =>
      (
        await api.get<DeliverySettlements>(DELIVERY(clientId), {
          params: { month },
        })
      ).data,
    enabled,
    retry: false,
  });
}

export function useDecideIntegrationCost(clientId: number, month: string) {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async ({
      costId,
      approve,
    }: {
      costId: number;
      approve: boolean;
    }) =>
      (
        await api.post<DeliverySettlements>(
          `${DELIVERY(clientId)}/integration-costs/${costId}/${approve ? "approve" : "reject"}`,
          null,
          { params: { month } },
        )
      ).data,
    onSuccess: invalidate,
  });
}

// ── Dodatki do rozliczenia kontraktora ──────────────────────────────────────

/** Plik dodatku (paragon, bilety, faktura kosztowa). */
export async function fetchExtraDocument(contractId: number, extraId: number, documentId: number): Promise<Blob> {
  return (
    await api.get<Blob>(`${BASE}/contract/${contractId}/extras/${extraId}/documents/${documentId}`, {
      responseType: "blob",
    })
  ).data;
}

// ── Akceptacja klienta po zbiorczej wysyłce KCP (E6.5, Bank Pocztowy) ─────────

export interface ClientAcceptancePerson extends ClientAcceptanceSummary {
  contract_id: number;
  person: string;
}

export interface ClientAcceptanceBatch {
  sent_at: string;
  people: number;
  accepted: number;
  accepted_at: string | null;
  reply: string | null;
}

export interface ClientAcceptanceMonth {
  enabled: boolean;
  client_id: number;
  month: string;
  email?: string;
  subject?: string;
  /** Treść maila do skopiowania (osoby do wysłania). */
  body?: string;
  people?: ClientAcceptancePerson[];
  batches?: ClientAcceptanceBatch[];
  counts?: Record<ClientAcceptanceState, number>;
}

export function useClientAcceptance(clientId: number | null, month: string) {
  return useQuery({
    queryKey: settlementKeys.clientAcceptance(clientId ?? 0, month),
    queryFn: async () =>
      (
        await api.get<ClientAcceptanceMonth>(`${BASE}/client-acceptance`, {
          params: { client_id: clientId, month },
        })
      ).data,
    enabled: clientId != null,
  });
}

interface AcceptanceChange {
  clientId: number;
  month: string;
  contractIds: number[];
}

function useAcceptanceChange(path: "sent" | "accept") {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ clientId, month, contractIds }: AcceptanceChange) =>
      (
        await api.post<Record<string, number>>(
          `${BASE}/client-acceptance/${path}`,
          { client_id: clientId, month, contract_ids: contractIds },
        )
      ).data,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["client-settlements"] }),
  });
}

/** Paczka wysłana z Outlooka: osoby czekają na akceptację klienta. */
export function useMarkAcceptanceSent() {
  return useAcceptanceChange("sent");
}

/** „Klient zaakceptował”, gdy NEXUS nie odczytał odpowiedzi sam. */
export function useAcceptByClient() {
  return useAcceptanceChange("accept");
}

/** Odpowiedź klienta (MSG albo EML) wgrana ręcznie. */
export function useUploadAcceptanceReply(month: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("month", month);
      form.append("file", file);
      return (
        await api.post<{ document_id: number; recognized: boolean }>(
          `${BASE}/client-acceptance/reply`,
          form,
          { headers: { "Content-Type": "multipart/form-data" } },
        )
      ).data;
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["client-settlements"] }),
  });
}

/** Zip z KCP w PDF; domyślnie osoby jeszcze niewysłane do klienta. */
export async function fetchAcceptancePackage(
  clientId: number,
  month: string,
): Promise<Blob> {
  return (
    await api.get<Blob>(`${BASE}/client-acceptance/package`, {
      params: { client_id: clientId, month },
      responseType: "blob",
    })
  ).data;
}

export interface NewExtraInput {
  contractId: number;
  kind: SettlementExtraKind;
  amount: string;
  description: string;
  billToClient: boolean;
}

/** Dodatek wpisany przez Finanse — od razu zatwierdzony. */
export function useAddSettlementExtra(month: string) {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async ({ contractId, kind, amount, description, billToClient }: NewExtraInput) =>
      (
        await api.post<SettlementDetail>(`${BASE}/contract/${contractId}/extras`, {
          month,
          kind,
          amount,
          description: description || null,
          bill_to_client: billToClient,
        })
      ).data,
    onSuccess: invalidate,
  });
}

export type ExtraDecision =
  | { action: "approve"; billToClient?: boolean }
  | { action: "reject"; reason: string }
  | { action: "billing"; billToClient: boolean };

export function useDecideSettlementExtra(month: string) {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async ({ contractId, extraId, decision }: { contractId: number; extraId: number; decision: ExtraDecision }) => {
      const url = `${BASE}/contract/${contractId}/extras/${extraId}/${decision.action}`;
      const body =
        decision.action === "reject"
          ? { reason: decision.reason }
          : { bill_to_client: decision.billToClient ?? null };
      return (await api.post<SettlementDetail>(url, body, { params: { month } })).data;
    },
    onSuccess: invalidate,
  });
}

export function useUploadExtraDocument(month: string) {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async ({ contractId, extraId, file }: { contractId: number; extraId: number; file: File }) => {
      const form = new FormData();
      form.append("file", file);
      return (
        await api.post<SettlementDetail>(`${BASE}/contract/${contractId}/extras/${extraId}/documents`, form, {
          params: { month },
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: invalidate,
  });
}

/** KCP osoby w PDF (od konsultanta albo złożona z eksportu Redmine). */
export async function fetchContractKcp(
  contractId: number,
  month: string,
): Promise<Blob> {
  return (
    await api.get<Blob>(`${BASE}/contract/${contractId}/kcp`, {
      params: { month },
      responseType: "blob",
    })
  ).data;
}

// ── Kontrola miesiąca: rozbieżności faktur klient ↔ konsultant (0784) ──────

export type MonthCheckKind = "hours_mismatch" | "cost_without_sale" | "sale_without_cost" | "over_working_days";
export type MonthCheckState = "new" | "to_correct" | "explained" | "closed";
export type MonthCheckAction = "explained" | "to_correct" | "new";

export interface MonthCheckInvoice {
  number: string;
  issue_date?: string;
  net?: string | null;
  correction?: boolean;
}

export interface MonthCheckCase {
  id: number;
  kind: MonthCheckKind;
  kind_label: string;
  month: string;
  candidate_id: number;
  person: string;
  contract_id: number | null;
  client_id: number | null;
  client: string;
  /** `null` bez dostępu do kwot albo gdy kwoty nie da się policzyć (brak stawki). */
  amount: string | null;
  currency: string;
  data_issue: "no_contract" | "no_order" | null;
  data_issue_label: string | null;
  details: {
    client_hours?: string | null;
    client_net?: string | null;
    sales_invoices?: string[];
    contractor_net?: string | null;
    contractor_invoices?: MonthCheckInvoice[];
    contractor_hours?: string | null;
    expected_cost?: string | null;
    cost_rate?: string | null;
    working_days?: number;
    limit_hours?: string;
    excess_hours?: string;
  };
  state: MonthCheckState;
  reason: string | null;
  decided_at: string | null;
  first_seen_at: string | null;
  closed_at: string | null;
}

export interface MonthCheckSummary {
  person_months: number | null;
  matched: number | null;
  skipped: Record<string, number>;
  overtime_confirmed: number | null;
  cases: number;
  cases_amount: string | null;
  open: number;
  open_amount: string | null;
  by_state: Record<MonthCheckState, number>;
  by_kind: Record<MonthCheckKind, number>;
  /** Sprawy z kwotą w innej walucie niż zł — poza sumami. */
  foreign_currency?: number;
}

export interface MonthCheckView {
  month: string;
  /** Chwila przebiegu, który policzył ten miesiąc; `null` — jeszcze nie sprawdzony. */
  checked_at: string | null;
  /** Do tego dnia (15. następnego miesiąca) brak faktury po jednej stronie to jeszcze nie sprawa. */
  waits_until: string | null;
  summary: MonthCheckSummary;
  cases: MonthCheckCase[];
  amounts: boolean;
}

export const monthCheckKey = (month: string) => ["client-settlements", "month-check", month] as const;

export function useMonthCheck(month: string) {
  return useQuery({
    queryKey: monthCheckKey(month),
    queryFn: async () => (await api.get<MonthCheckView>(`${BASE}/month-check`, { params: { month } })).data,
  });
}

export function useMonthCheckDecision(month: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: { id: number; action: MonthCheckAction; reason?: string }) =>
      (
        await api.post<MonthCheckCase>(`${BASE}/month-check/${input.id}/decision`, {
          action: input.action,
          reason: input.reason ?? null,
        })
      ).data,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: monthCheckKey(month) });
    },
  });
}
