// Księgowość → księga NEXUSA (K1, 0700): dokumenty, dziennik, obroty, plan kont.
//
// Lustro `backend/app/api/ledger.py`. Bramki: „Moduł Finanse” i przełącznik
// modułu `ledger` (wyłączony = 404, admin widzi zawsze). Kto zatwierdza, robi
// storno i zamyka okres (lista „Księgowi” albo admin), liczy serwer —
// front pokazuje przyciski po polach `me` i `can_*`.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { hasPermission } from "@/lib/permissions";

const BASE = "/api/accounting";

export type DocType = "FVS" | "FVZ" | "WB" | "LP" | "AM" | "RMK" | "VAT" | "PK" | "BO" | "ST";
export type DocStatus = "draft" | "approved";
export type Side = "debit" | "credit";
export type YearMode = "symfonia" | "parallel" | "nexus";
export type ModuleKey = "ledger" | "automations" | "bank" | "vat" | "assets" | "payroll" | "reports";

export interface LedgerModule {
  key: ModuleKey;
  label: string;
  replaces: string;
  stage: string;
  built: boolean;
  enabled: boolean;
  open: boolean;
}

export interface LedgerPeriod {
  id: number;
  month: number;
  starts_on: string;
  ends_on: string;
  status: "open" | "closed";
  closed_at: string | null;
  reopened_at: string | null;
  reopen_reason: string | null;
  drafts: number;
  approved: number;
}

export interface LedgerYear {
  id: number;
  year: number;
  mode: YearMode;
  mode_label: string;
  status: "open" | "closed";
  journal_entries: number;
  periods: LedgerPeriod[];
}

export interface Option {
  code: string;
  label: string;
}

export interface SalesAccounts {
  receivable_account: string;
  revenue_account: string;
  vat_account: string;
}

export interface AllocationAccounts {
  settlement_account: string;
  client_account: string;
  front_office_account: string;
  back_office_account: string;
  overhead_account: string;
  /** Jedno konto kosztów zespołu na PK płacowe — pion tylko w MPK pozycji (D2). */
  team_account: string;
}

/** Konta listy płac z Enovy (K3c); PPK i inne potrącenia mogą zostać puste. */
export interface PayrollAccounts {
  wages_account: string;
  insurance_account: string;
  settlement_account: string;
  zus_account: string;
  pit_account: string;
  ppk_account: string;
  deductions_account: string;
}

export interface LedgerConfig {
  open: boolean;
  modules: LedgerModule[];
  me: { admin: boolean; approver: boolean; payroll: boolean };
  accountants: number[] | null;
  /** Konta dekretu faktur sprzedaży (K2), zmienia administrator. */
  sales_accounts: SalesAccounts;
  /** Konta rozliczenia kosztów na „5” (K2), zmienia administrator. */
  allocation_accounts: AllocationAccounts;
  /** Konta listy płac z Enovy (K3c), zmienia administrator. */
  payroll_accounts?: PayrollAccounts;
  years: LedgerYear[];
  today: string;
  doc_types: (Option & { manual: boolean })[];
  year_modes: Option[];
  account_kinds: string[];
  account_types: Option[];
  dictionaries: Option[];
}

export interface DocumentRow {
  id: number;
  doc_type: DocType;
  type_label: string;
  number: string;
  op_date: string;
  doc_date: string;
  description: string;
  counterparty: { id: number; name: string | null } | null;
  source: { type: string; id: string } | null;
  currency: string;
  fx_rate: string | null;
  fx_date: string | null;
  status: DocStatus;
  journal_no: number | null;
  debit_total: number;
  credit_total: number;
  sensitivity: "payroll" | null;
  reverses_id: number | null;
  reversed_by_id: number | null;
  created_by_name: string | null;
  created_at: string | null;
  approved_by_name: string | null;
  approved_at: string | null;
  can_edit: boolean;
  can_approve: boolean;
  can_reverse: boolean;
}

export interface DocumentLine {
  line_no: number;
  side: Side;
  side_label: "Wn" | "Ma";
  account: string;
  account_name: string | null;
  amount: number;
  currency: string;
  amount_cur: number | null;
  counterparty: { id: number; name: string | null } | null;
  mpk: string | null;
  description: string;
}

export interface DocumentEvent {
  action: string;
  label: string;
  actor_name: string | null;
  at: string | null;
  detail: Record<string, unknown>;
}

export interface DocumentCard extends DocumentRow {
  lines: DocumentLine[];
  events: DocumentEvent[];
}

export interface DocumentList {
  items: DocumentRow[];
  total: number;
  counts: Partial<Record<DocType, number>>;
  drafts: number;
  year: number | null;
}

export interface DocumentFilters {
  year: number;
  month: number | null;
  docType: DocType | null;
  status: DocStatus | null;
  q: string;
  offset: number;
}

export interface LineInput {
  side: Side;
  account: string;
  /** Złote z groszami jako tekst („1234.56”, minus dla storna czerwonego). */
  amount: string;
  description?: string;
  counterparty_id?: number | null;
  mpk?: string | null;
}

export interface DocumentInput {
  doc_type: "PK" | "BO";
  number?: string | null;
  op_date: string;
  doc_date?: string | null;
  description?: string;
  counterparty_id?: number | null;
  lines: LineInput[];
}

export interface ApproveResult {
  approved: { id: number; journal_no: number }[];
  refused: { id: number; status: number; detail: string }[];
}

export interface TrialRow {
  account: string;
  name: string;
  class: string;
  bo_wn: number;
  bo_ma: number;
  wn: number;
  ma: number;
  ytd_wn: number;
  ytd_ma: number;
  saldo_wn: number;
  saldo_ma: number;
  analytics: number;
}

export interface TrialBalance {
  year: number;
  month_from: number;
  month_to: number;
  level: "synthetic" | "analytic";
  items: TrialRow[];
  totals: Record<"bo_wn" | "bo_ma" | "wn" | "ma" | "ytd_wn" | "ytd_ma" | "saldo_wn" | "saldo_ma", number>;
  balanced: boolean;
}

export interface CardLine {
  journal_no: number;
  document_id: number;
  doc_type: DocType;
  number: string;
  op_date: string;
  description: string;
  account: string;
  wn: number;
  ma: number;
  balance: number;
}

export interface AccountCard {
  account: string;
  name: string | null;
  dictionary: string | null;
  year: number;
  month_from: number;
  month_to: number;
  opening: number;
  closing: number;
  items: CardLine[];
  /** Na koncie są zapisy płacowe, których ta osoba nie widzi — saldo jest bez nich (D2). */
  payroll_hidden: boolean;
  truncated: boolean;
}

export interface ChartAccount {
  id: number;
  number: string;
  name: string;
  kind: string;
  kind_label: string;
  active: boolean;
  parent_number: string | null;
  account_type: string | null;
  account_type_label: string | null;
  dictionary: string | null;
  dictionary_label: string | null;
  report_line: string | null;
  class: string;
  has_children: boolean;
  postable: boolean;
  used: number;
  in_rules: number;
}

export interface AccountInput {
  number?: string;
  name?: string;
  kind?: string | null;
  account_type?: string | null;
  parent_number?: string | null;
  dictionary?: string | null;
  report_line?: string | null;
  active?: boolean;
}

export interface OpeningPreview {
  year: number;
  rows: number;
  skipped: number;
  errors: { line: number; message: string }[];
  debit_total: number;
  credit_total: number;
  balanced: boolean;
  missing_accounts: string[];
  missing_total: number;
  counterparties_matched: number;
  problems: string[];
  preview: { account: string; name: string; side: Side; amount: number }[];
  saved: boolean;
  document_id: number | null;
}

export type SourceKind = "costs" | "sales" | "allocation" | "recurring" | "prepayments";

export interface RecurringLine {
  side: Side;
  account: string;
  amount: number;
  mpk: string | null;
  counterparty_id: number | null;
  description: string;
}

/** Wzór PK cyklicznego (K3a); daty miesięcy „RRRR-MM”. */
export interface RecurringTemplate {
  id: number;
  name: string;
  description: string;
  lines: RecurringLine[];
  total: number;
  start_month: string;
  end_month: string | null;
  active: boolean;
  draft: number;
  approved: number;
  last_approved: string | null;
}

/** RMK czynne — koszt rozliczany ratami (K3a). */
export interface Prepayment {
  id: number;
  name: string;
  reference: string;
  counterparty: { id: number; name: string | null } | null;
  cost_account: string;
  prepaid_account: string;
  mpk: string | null;
  total_amount: number;
  start_month: string;
  months: number;
  installment: number;
  active: boolean;
  draft: number;
  approved: number;
  last_approved: string | null;
}

export interface AutomationsOverview {
  recurring: RecurringTemplate[];
  prepayments: Prepayment[];
}

export interface RecurringInput {
  name?: string;
  description?: string;
  lines?: LineInput[];
  start_month?: string;
  end_month?: string | null;
}

export interface PrepaymentInput {
  name: string;
  reference: string;
  cost_account: string;
  prepaid_account: string;
  mpk: string | null;
  total_amount: string;
  start_month: string;
  months: number;
}

export interface AllocationDetail {
  code: string;
  label: string;
  /** Grosze; ujemne = korekty przeważają w tym MPK. */
  amount: number;
  payroll: boolean;
}

export interface SourceProblem {
  source_id: string;
  label: string;
  problems: string[];
}

/** Źródło miesiąca (K2): ile faktur, ile już w księdze, co czeka, co blokuje. */
export interface SourceSummary {
  kind: SourceKind;
  label: string;
  total: number;
  draft: number;
  approved: number;
  to_post: number;
  changed: number;
  skipped: number;
  problems: SourceProblem[];
  problems_total: number;
  /** Faktury osób zespołu księguje osoba z Płacami — bez liczby (D2). */
  payroll_hidden: boolean;
  /** Rozliczenie kosztów: kwoty MPK z zatwierdzonych FVZ. */
  details?: AllocationDetail[];
  /** Rozliczenie kosztów: FVZ okresu w buforze (wejdą po zatwierdzeniu). */
  pending_costs?: number;
}

export interface SourcesMonth {
  year: number;
  month: number;
  year_exists: boolean;
  period_open: boolean;
  sales_accounts: SalesAccounts;
  items: SourceSummary[];
}

export interface SyncResult {
  kind: SourceKind;
  created: number;
  rebuilt: number;
  deleted: number;
  unchanged: number;
  skipped: number;
  problems: SourceProblem[];
  problems_total: number;
}

// ── Paczki do Symfonii (K3b) ────────────────────────────────────────────────

export type ExportKind =
  | "manual"
  | "recurring"
  | "prepayments"
  | "allocation"
  | "costs"
  | "sales"
  | "opening"
  | "other";
export type ExportStatus = "exported" | "booked" | "cancelled";

export interface ExportKindRow {
  key: ExportKind;
  label: string;
  /** W paczce domyślnie — reszta trafia do Symfonii inną drogą. */
  default: boolean;
  note: string | null;
  count: number;
  debit_total: number;
  /** Dokumenty płacowe (D2) — tylko dla osoby z Płacami, osobną paczką. */
  payroll_count: number;
  payroll_debit_total: number;
}

export interface ExportDocument {
  id: number;
  journal_no: number;
  number: string;
  doc_type: DocType;
  op_date: string;
  description: string;
  debit_total: number;
  kind: ExportKind;
  payroll: boolean;
}

export interface LedgerExportItem {
  id: number;
  number: string;
  status: ExportStatus;
  status_label: string;
  kinds: ExportKind[];
  kind_labels: string[];
  file_format: string;
  file_format_label: string;
  file_name: string;
  file_sha256: string;
  document_count: number;
  debit_total: number;
  has_payroll: boolean;
  created_at: string | null;
  created_by: string | null;
  booked_at: string | null;
  booked_by: string | null;
  cancelled_at: string | null;
  cancelled_by: string | null;
}

export interface ExportsOverview {
  year: number;
  month: number;
  book_year: { mode: YearMode; mode_label: string } | null;
  period_status: "open" | "closed" | null;
  exportable: boolean;
  refusal: string | null;
  kinds: ExportKindRow[];
  documents: ExportDocument[];
  drafts: number;
  exports: LedgerExportItem[];
  formats: { key: string; label: string }[];
  default_format: string;
}

export interface CreateExportInput {
  year: number;
  month: number;
  kinds: ExportKind[];
  file_format: string;
  payroll: boolean;
}

// ── Lista płac z Enovy (K3c) ───────────────────────────────────────────────

export interface PayrollListLine {
  side: Side;
  account: string;
  amount: number;
  mpk: string | null;
  description: string;
}

export interface PayrollListPreview {
  rows: number;
  skipped: number;
  columns: { key: string; label: string; header: string }[];
  totals: Record<"gross" | "employee" | "employer" | "zus" | "pit" | "ppk" | "deductions" | "net", number>;
  mpk: { mpk: string | null; gross: number; employer: number }[];
  lines: PayrollListLine[];
  errors: { line: number; message: string }[];
  errors_total: number;
  warnings: { line: number; message: string }[];
  warnings_total: number;
  problems: string[];
  saved: boolean;
  document: { id: number; number: string } | null;
}

export interface PayrollListInput {
  file: File;
  year: number;
  month: number;
  list: string;
  paymentDate: string | null;
  save: boolean;
}

// ── Lista zamknięcia miesiąca (K3d) ────────────────────────────────────────

export type ClosingState = "ok" | "todo" | "problem" | "later";

export interface ClosingCheck {
  key: string;
  label: string;
  state: ClosingState;
  detail: string;
  href: string | null;
}

export interface ClosingDeadline {
  key: "zus" | "ppk" | "pit" | "vat";
  label: string;
  /** Dzień z ustawy (15., 20., 25.) i termin po przesunięciu na dzień roboczy. */
  nominal: string;
  due: string;
  basis: string;
  amount_from: string;
}

export interface ClosingMonth {
  year: number;
  month: number;
  period_status: "open" | "closed" | null;
  items: ClosingCheck[];
  deadlines: ClosingDeadline[];
}

export const accountingKeys = {
  all: ["accounting"] as const,
  config: ["accounting", "config"] as const,
  documents: ["accounting", "documents"] as const,
  list: (filters: DocumentFilters) => ["accounting", "documents", "list", filters] as const,
  card: (id: number) => ["accounting", "documents", "card", id] as const,
  trial: (year: number, from: number, to: number, level: string) =>
    ["accounting", "trial", year, from, to, level] as const,
  accountCard: (account: string, year: number, from: number, to: number) =>
    ["accounting", "account-card", account, year, from, to] as const,
  chart: ["accounting", "chart"] as const,
  candidates: ["accounting", "candidates"] as const,
  sources: (year: number, month: number) => ["accounting", "sources", year, month] as const,
  automations: ["accounting", "automations"] as const,
  exports: (year: number, month: number) => ["accounting", "exports", year, month] as const,
  closing: (year: number, month: number) => ["accounting", "closing", year, month] as const,
};

export const DOCUMENT_PAGE = 50;

export function useLedgerConfig(enabled = true) {
  return useQuery({
    queryKey: accountingKeys.config,
    queryFn: async () => (await api.get<LedgerConfig>(`${BASE}/config`)).data,
    staleTime: 60 * 1000,
    enabled,
  });
}

export function useDocuments(filters: DocumentFilters, enabled = true) {
  return useQuery({
    queryKey: accountingKeys.list(filters),
    queryFn: async () =>
      (
        await api.get<DocumentList>(`${BASE}/documents`, {
          params: {
            year: filters.year,
            month: filters.month ?? undefined,
            doc_type: filters.docType ?? undefined,
            status: filters.status ?? undefined,
            q: filters.q.trim() || undefined,
            offset: filters.offset,
            limit: DOCUMENT_PAGE,
          },
        })
      ).data,
    placeholderData: (previous) => previous,
    enabled,
  });
}

export function useDocumentCard(id: number | null) {
  return useQuery({
    queryKey: accountingKeys.card(id ?? 0),
    queryFn: async () => (await api.get<DocumentCard>(`${BASE}/documents/${id}`)).data,
    enabled: id != null && id > 0,
  });
}

function useInvalidateLedger() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: accountingKeys.all });
}

export function useCreateDocument() {
  const invalidate = useInvalidateLedger();
  return useMutation({
    mutationFn: async (body: DocumentInput) =>
      (await api.post<DocumentCard>(`${BASE}/documents`, body)).data,
    onSuccess: () => invalidate(),
  });
}

export function useUpdateDocument(id: number) {
  const invalidate = useInvalidateLedger();
  return useMutation({
    mutationFn: async (body: DocumentInput) =>
      (await api.patch<DocumentCard>(`${BASE}/documents/${id}`, body)).data,
    onSuccess: () => invalidate(),
  });
}

export function useDeleteDocument() {
  const invalidate = useInvalidateLedger();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`${BASE}/documents/${id}`);
      return id;
    },
    onSuccess: () => invalidate(),
  });
}

export function useApproveDocuments() {
  const invalidate = useInvalidateLedger();
  return useMutation({
    mutationFn: async (ids: number[]) =>
      (await api.post<ApproveResult>(`${BASE}/documents/approve`, { ids })).data,
    onSettled: () => invalidate(),
  });
}

export function useReverseDocument() {
  const invalidate = useInvalidateLedger();
  return useMutation({
    mutationFn: async (args: { id: number; reason: string; op_date?: string | null }) =>
      (
        await api.post<DocumentCard>(`${BASE}/documents/${args.id}/reverse`, {
          reason: args.reason,
          op_date: args.op_date ?? undefined,
        })
      ).data,
    onSuccess: () => invalidate(),
  });
}

export function useTrialBalance(
  year: number | null,
  monthFrom: number,
  monthTo: number,
  level: "synthetic" | "analytic",
) {
  return useQuery({
    queryKey: accountingKeys.trial(year ?? 0, monthFrom, monthTo, level),
    queryFn: async () =>
      (
        await api.get<TrialBalance>(`${BASE}/trial-balance`, {
          params: { year, month_from: monthFrom, month_to: monthTo, level },
        })
      ).data,
    enabled: year != null,
    placeholderData: (previous) => previous,
  });
}

export function useAccountCard(
  account: string | null,
  year: number | null,
  monthFrom: number,
  monthTo: number,
) {
  return useQuery({
    queryKey: accountingKeys.accountCard(account ?? "", year ?? 0, monthFrom, monthTo),
    queryFn: async () =>
      (
        await api.get<AccountCard>(`${BASE}/accounts/card`, {
          params: { account, year, month_from: monthFrom, month_to: monthTo },
        })
      ).data,
    enabled: Boolean(account) && year != null,
  });
}

export function useChart(enabled = true) {
  return useQuery({
    queryKey: accountingKeys.chart,
    queryFn: async () => (await api.get<{ items: ChartAccount[] }>(`${BASE}/chart`)).data.items,
    enabled,
  });
}

export function useCreateAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: AccountInput) =>
      (await api.post<{ items: ChartAccount[] }>(`${BASE}/chart`, body)).data.items,
    onSuccess: (items) => client.setQueryData(accountingKeys.chart, items),
  });
}

export function useUpdateAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (args: { id: number; changes: AccountInput }) =>
      (await api.patch<{ items: ChartAccount[] }>(`${BASE}/chart/${args.id}`, args.changes)).data
        .items,
    onSuccess: (items) => client.setQueryData(accountingKeys.chart, items),
  });
}

function useConfigMutation<TArgs>(request: (args: TArgs) => Promise<unknown>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSettled: () => client.invalidateQueries({ queryKey: accountingKeys.all }),
  });
}

export function useSetModule() {
  return useConfigMutation((args: { module: ModuleKey; enabled: boolean }) =>
    api.put(`${BASE}/config/modules`, args),
  );
}

export function useSetAccountants() {
  return useConfigMutation((userIds: number[]) =>
    api.put(`${BASE}/config/accountants`, { user_ids: userIds }),
  );
}

export function useAccountantCandidates(enabled: boolean) {
  return useQuery({
    queryKey: accountingKeys.candidates,
    queryFn: async () =>
      (
        await api.get<{ items: { id: number; name: string | null; admin: boolean }[] }>(
          `${BASE}/config/candidates`,
        )
      ).data.items,
    enabled,
  });
}

export function useCreateYear() {
  return useConfigMutation((args: { year: number; mode?: YearMode }) =>
    api.post(`${BASE}/years`, args),
  );
}

export function useSetYearMode() {
  return useConfigMutation((args: { id: number; mode: YearMode }) =>
    api.patch(`${BASE}/years/${args.id}`, { mode: args.mode }),
  );
}

export function useClosePeriod() {
  return useConfigMutation((periodId: number) => api.post(`${BASE}/periods/${periodId}/close`));
}

export function useReopenPeriod() {
  return useConfigMutation((args: { periodId: number; reason: string }) =>
    api.post(`${BASE}/periods/${args.periodId}/reopen`, { reason: args.reason }),
  );
}

export function useSources(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: accountingKeys.sources(year, month),
    queryFn: async () =>
      (await api.get<SourcesMonth>(`${BASE}/sources`, { params: { year, month } })).data,
    enabled,
  });
}

export function useSyncSources() {
  const invalidate = useInvalidateLedger();
  return useMutation({
    mutationFn: async (args: { kind: SourceKind; year: number; month: number }) =>
      (await api.post<SyncResult>(`${BASE}/sources/sync`, args)).data,
    onSettled: () => invalidate(),
  });
}

export function useSetSalesAccounts() {
  return useConfigMutation((args: SalesAccounts) => api.put(`${BASE}/config/sales`, args));
}

export function useAutomations(enabled = true) {
  return useQuery({
    queryKey: accountingKeys.automations,
    queryFn: async () => (await api.get<AutomationsOverview>(`${BASE}/automations`)).data,
    enabled,
  });
}

/** Zapis wzoru PK cyklicznego albo RMK; odpowiedź = świeży przegląd automatów. */
export function useSaveAutomation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (
      args:
        | { kind: "recurring"; id?: number; body: RecurringInput }
        | { kind: "prepayments"; id?: number; body: PrepaymentInput },
    ) => {
      const path = `${BASE}/automations/${args.kind}${args.id ? `/${args.id}` : ""}`;
      const response = args.id
        ? await api.patch<AutomationsOverview>(path, args.body)
        : await api.post<AutomationsOverview>(path, args.body);
      return response.data;
    },
    onSuccess: (data) => {
      client.setQueryData(accountingKeys.automations, data);
      // Zapis i usunięcie zdejmują szkice wzoru z bufora — odświeża się cała
      // księga (źródła, dokumenty, liczniki okresów, lista zamknięcia).
      client.invalidateQueries({ queryKey: accountingKeys.all });
    },
  });
}

export function useRemoveAutomation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (args: { kind: "recurring" | "prepayments"; id: number }) =>
      (await api.delete<AutomationsOverview>(`${BASE}/automations/${args.kind}/${args.id}`)).data,
    onSuccess: (data) => {
      client.setQueryData(accountingKeys.automations, data);
      // Zapis i usunięcie zdejmują szkice wzoru z bufora — odświeża się cała
      // księga (źródła, dokumenty, liczniki okresów, lista zamknięcia).
      client.invalidateQueries({ queryKey: accountingKeys.all });
    },
  });
}

export function useOpeningImport() {
  const invalidate = useInvalidateLedger();
  return useMutation({
    mutationFn: async ({ file, year, save }: { file: File; year: number; save: boolean }) => {
      const form = new FormData();
      form.append("file", file);
      return (
        await api.post<OpeningPreview>(`${BASE}/opening/import`, form, {
          params: { year, save },
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: (data) => {
      if (data.saved) invalidate();
    },
  });
}

export function useSetPayrollAccounts() {
  return useConfigMutation((args: PayrollAccounts) => api.put(`${BASE}/config/payroll`, args));
}

export function usePayrollListImport() {
  const invalidate = useInvalidateLedger();
  return useMutation({
    mutationFn: async ({ file, year, month, list, paymentDate, save }: PayrollListInput) => {
      const form = new FormData();
      form.append("file", file);
      const params: Record<string, string | number | boolean> = { year, month, list, save };
      if (paymentDate) params.payment_date = paymentDate;
      return (
        await api.post<PayrollListPreview>(`${BASE}/payroll-lists/import`, form, {
          params,
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: (data) => {
      if (data.saved) invalidate();
    },
  });
}

export function useSetAllocationAccounts() {
  return useConfigMutation((args: AllocationAccounts) => api.put(`${BASE}/config/allocation`, args));
}

export function useExports(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: accountingKeys.exports(year, month),
    queryFn: async () =>
      (await api.get<ExportsOverview>(`${BASE}/exports`, { params: { year, month } })).data,
    enabled,
  });
}

/** Ścieżka pliku paczki (pobranie z sesją przez `downloadAuthenticatedFile`). */
export function exportFilePath(id: number): string {
  return `${BASE}/exports/${id}/file`;
}

/** Paczka zmienia też listę zamknięcia miesiąca (pozycja „Paczka do Symfonii”). */
function useInvalidateExports() {
  const client = useQueryClient();
  return () => {
    client.invalidateQueries({ queryKey: ["accounting", "exports"] });
    client.invalidateQueries({ queryKey: ["accounting", "closing"] });
  };
}

export function useCreateExport() {
  const invalidate = useInvalidateExports();
  return useMutation({
    mutationFn: async (args: CreateExportInput) =>
      (await api.post<LedgerExportItem>(`${BASE}/exports`, args)).data,
    onSettled: () => invalidate(),
  });
}

export function useChangeExport() {
  const invalidate = useInvalidateExports();
  return useMutation({
    mutationFn: async (args: { id: number; action: "book" | "cancel" }) =>
      (await api.post<LedgerExportItem>(`${BASE}/exports/${args.id}/${args.action}`)).data,
    onSettled: () => invalidate(),
  });
}

export function useClosing(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: accountingKeys.closing(year, month),
    queryFn: async () =>
      (await api.get<ClosingMonth>(`${BASE}/closing`, { params: { year, month } })).data,
    enabled,
  });
}

/** Pozycja „Księgowość” w menu: „Moduł Finanse” i otwarty moduł księgi. */
export function useAccountingNavOpen(user: Parameters<typeof hasPermission>[0]): boolean {
  const config = useLedgerConfig(hasPermission(user, "finance_module"));
  return config.data?.open === true;
}
