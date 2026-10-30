// „Ludzie w NEXUSIE” (16.10.2026) — Płace i premie.
//
// Lustro `backend/app/api/hr_payroll.py`. Zakres liczy serwer (D2): Płace widzą
// stawki i kwoty wszystkich, osoba swoje, przełożony godziny i premie zespołu
// bez stawek — odpowiedź dla przełożonego po prostu nie ma tych pól. Kwoty
// przychodzą jako tekst dziesiętny ("1234.50"); formatuje je `payroll-format.ts`.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { EmploymentType } from "@/lib/api/hr";
import { paymentKeys } from "@/lib/api/hr-payments";
import { settlementKeys } from "@/lib/api/hr-settlements";
import type { TimesheetStatus } from "@/lib/api/hr-time";

export type Currency = "PLN" | "EUR" | "USD";
export type BonusCategory = "sales" | "delivery_lead" | "recruiter" | "custom" | "league";
export type BonusStatus = "proposed" | "assigned" | "cancelled";
export type BonusSource = "manual" | "contract_placement" | "league" | "compass_import";
export type PeriodStatus = "open" | "closed";
export type { TimesheetStatus };

export interface RateRow {
  id: number;
  user_id: number;
  hourly_rate: string;
  currency: Currency;
  effective_from: string;
  effective_to: string | null;
  reason: string | null;
  set_by: number | null;
  /**
   * Odpowiedź zapisu: ostrzeżenie bez blokady (zlecenie bez minimum dla roku
   * albo stawka w innej walucie niż złoty — etap 2, D7).
   */
  warning?: string | null;
}

/** Minimalna stawka godzinowa na zleceniu per rok (zł brutto) — D7. */
export interface MinimumRates {
  rates: { year: number; hourly_rate: string }[];
  currency: "PLN";
}

/** Oznaczenie „Do sprawdzenia” (tylko Płace): nic nie blokuje, odznacza wiersz. */
export interface BonusFlag {
  code: string;
  label: string;
  detail: string;
}

/** Etapy placementu dla osoby: podpis, kontrakt, zamówienie, start. */
export interface BonusStageFacts {
  signed: boolean;
  contract_active: boolean;
  order: boolean;
  started: boolean;
  start_date: string | null;
}

export interface MissingRateContract {
  contract_id: number;
  candidate: string;
  client: string;
  start_date: string;
  recruiter_name: string | null;
  dl_name: string | null;
}

export interface BonusRow {
  id: number;
  recipient_user_id: number;
  recipient_name: string | null;
  proposed_by: number | null;
  proposed_by_name: string | null;
  amount: string;
  currency: Currency;
  category: BonusCategory;
  category_label: string;
  period_year: number;
  period_month: number;
  status: BonusStatus;
  source: BonusSource;
  contract_id: number | null;
  eligible_on: string | null;
  /** Czy termin premii (start + 21 dni roboczych) już minął. */
  eligible?: boolean;
  description: string | null;
  assigned_by: number | null;
  /** Tylko „Mój czas” (`/me`): kto przyznał premię. */
  assigned_by_name?: string | null;
  /** Tylko „Mój czas” (`/me`): miesiąc premii zamknięty w płacach (rozliczona). */
  period_closed?: boolean;
  assigned_at: string | null;
  cancelled_at: string | null;
  /** `manual` albo kod automatu (`contract_ended`, `contract_void`, …). */
  cancel_reason: string | null;
  /** Kwota propozycji automatu poprawiona ręcznie. */
  edited: boolean;
  /** Widok miesiąca: przyznana premia z placementu, a kontrakt skończył się przed terminem. */
  contract_ended_early?: boolean;
  /** Osoba zmieniona ręcznie przez Płace (automat jej nie nadpisuje). */
  edited_recipient?: boolean;
  flags?: BonusFlag[];
  stages?: BonusStageFacts;
  /** Tylko dla Płac: reguły i liczby, z których wyszła kwota. */
  rule_snapshot?: Record<string, unknown>;
  /** Listy Płac: czy widz może zatwierdzić propozycję (ręczną przełożonego — tylko Płace). */
  can_approve?: boolean;
  /** Propozycje „liczy się”: postęp do terminu. */
  business_days_elapsed?: number | null;
  business_days_required?: number;
}

export interface PayrollLine {
  currency: Currency;
  hourly_rate: string | null;
  hours_amount: string | null;
  bonus_total: string;
  total: string;
}

export interface PayrollPerson {
  user_id: number;
  name: string;
  employment_type: EmploymentType | null;
  timesheet_required: boolean;
  timesheet_status: TimesheetStatus | null;
  hours: string;
  overtime_hours: string;
  paid_leave_days: string;
  other_leave_days: string;
  /** Tylko Płace. */
  rate_missing?: boolean;
  lines?: PayrollLine[];
  /** Przełożony: same premie, bez stawek i kwot wynagrodzenia. */
  bonuses?: { currency: Currency; bonus_total: string }[];
}

export interface CloseWarning {
  code: "unapproved_timesheets" | "missing_rates";
  message: string;
  count: number;
  people: { user_id: number; name: string; timesheet_status?: TimesheetStatus | null }[];
}

export interface PayrollMonthSummary {
  year: number;
  month: number;
  label: string;
  status: PeriodStatus;
  people: number;
  totals: Record<string, string>;
  pending_proposals: number;
  can_close: boolean;
}

export interface PayrollMonthDetail {
  year: number;
  month: number;
  label: string;
  status: PeriodStatus;
  frozen: boolean;
  scope: "payroll" | "team";
  closed_at: string | null;
  reopened_at: string | null;
  reopen_reason: string | null;
  can_close: boolean;
  can_reopen: boolean;
  stats: {
    people: number;
    timesheets_approved: number;
    timesheets_submitted: number;
    timesheets_missing: number;
    proposals: number;
  };
  people: PayrollPerson[];
  bonuses: BonusRow[];
  in_progress: BonusRow[];
  /** Tylko Płace: propozycje z późniejszych miesięcy. */
  later?: BonusRow[];
  /** Tylko Płace: kontrakty, którym nie da się policzyć marży. */
  missing_rates?: MissingRateContract[];
  totals?: Record<string, string>;
  warnings?: CloseWarning[];
}

/**
 * Premia „w drodze” z podpisanego kontraktu, której automat jeszcze nie
 * założył (D2): szacunek z tych samych reguł, nic nie jest zapisane.
 */
export interface BonusForecast {
  stages?: BonusStageFacts | null;
  key: string;
  contract_id: number;
  role: "dl" | "dl_extra" | "recruiter";
  category: BonusCategory;
  category_label: string;
  description: string;
  /** `null` = brak stawki klienta albo kursu — kwoty jeszcze nie da się policzyć. */
  amount: string | null;
  currency: Currency;
  amount_missing_reason: "missing_rates" | "fx_missing" | null;
  start_date: string;
  started: boolean;
  /** „~ od” — start + 21 dni roboczych. */
  eligible_on: string;
  business_days_elapsed: number;
  business_days_required: number;
}

export interface MyPayroll {
  current_rate: RateRow | null;
  rates: RateRow[];
  bonuses: BonusRow[];
  forecast?: BonusForecast[];
  business_days_required?: number;
}

export interface SettlementMonth {
  year: number;
  month: number;
  label: string;
  /** `true` = linie zamrożone przez Płace; `false` = szacunek, zmienia się do zamknięcia. */
  final: boolean;
  hours: string;
  hours_source: "frozen" | "approved" | "entered" | "none";
  timesheet_status: TimesheetStatus | null;
  rate_missing: boolean;
  lines: PayrollLine[];
}

export interface MySettlement {
  year: number;
  months: SettlementMonth[];
  /** Premie z zamkniętych miesięcy roku (per waluta). */
  bonuses_paid: Record<string, string>;
}

export interface PersonPayroll {
  user_id: number;
  scope: "full" | "team";
  can_edit_rates: boolean;
  can_add_bonus: boolean;
  bonuses: BonusRow[];
  current_rate?: RateRow | null;
  rates?: RateRow[];
}

export interface ExtraDlRule {
  dl_user_id: number;
  recipient_user_id: number;
  dl_name?: string | null;
  recipient_name?: string | null;
}

export interface DlHoursRule {
  user_id: number;
  hours: number;
  name?: string | null;
}

export interface IndividualRecruiterRule {
  user_id: number;
  base_percent: string;
  step_percent: string;
  expert_percent: string;
  name?: string | null;
}

export interface BonusRules {
  recruiter_tier_bounds: [string, string];
  recruiter_tier_amounts: [string, string, string];
  dl_percent: string;
  monthly_hours: number;
  eligible_business_days: number;
  currency: Currency;
  extra_dl: ExtraDlRule[];
  dl_hours?: DlHoursRule[];
  individual_recruiters?: IndividualRecruiterRule[];
  automation_since: string | null;
  league_types: string[];
}

export interface RateInput {
  hourly_rate: string;
  currency: Currency;
  effective_from: string;
  reason?: string | null;
}

export interface BonusInput {
  recipient_user_id: number;
  amount: string;
  currency: Currency;
  category: BonusCategory;
  period_year: number;
  period_month: number;
  description?: string | null;
  contract_id?: number | null;
}

export type BonusPatch = Partial<BonusInput> & { change_reason?: string | null };

export interface PlacementOption {
  contract_id: number;
  label: string;
  start_date: string | null;
}

export interface BonusDecisions {
  signed: BonusRow[];
  league: BonusRow[];
  check: BonusRow[];
  vouchers: { id: number; label: string; period: string; rank: number; name: string }[];
}

export const payrollKeys = {
  all: ["hr", "payroll"] as const,
  me: ["hr", "payroll", "me"] as const,
  settlement: (year: number) => ["hr", "payroll", "me", "settlement", year] as const,
  months: ["hr", "payroll", "months"] as const,
  month: (year: number, month: number) => ["hr", "payroll", "month", year, month] as const,
  person: (userId: number) => ["hr", "payroll", "person", userId] as const,
  rules: ["hr", "payroll", "rules"] as const,
  minimumRates: ["hr", "payroll", "minimum-rates"] as const,
};

export const payrollPaths = {
  export: (year: number, month: number) =>
    `/api/hr/payroll/months/${year}/${month}/export.xlsx`,
};

export function useMyPayroll(enabled = true) {
  return useQuery({
    queryKey: payrollKeys.me,
    queryFn: async () => (await api.get<MyPayroll>("/api/hr/payroll/me")).data,
    enabled,
  });
}

export function useMySettlement(year: number, enabled = true) {
  return useQuery({
    queryKey: payrollKeys.settlement(year),
    queryFn: async () =>
      (await api.get<MySettlement>("/api/hr/payroll/me/settlement", { params: { year } }))
        .data,
    enabled,
  });
}

export function usePayrollMonths() {
  return useQuery({
    queryKey: payrollKeys.months,
    queryFn: async () =>
      (await api.get<{ items: PayrollMonthSummary[] }>("/api/hr/payroll/months")).data
        .items,
  });
}

export function usePayrollMonth(year: number, month: number) {
  return useQuery({
    queryKey: payrollKeys.month(year, month),
    queryFn: async () =>
      (await api.get<PayrollMonthDetail>(`/api/hr/payroll/months/${year}/${month}`)).data,
    enabled: Number.isFinite(year) && Number.isFinite(month),
  });
}

export function usePersonPayroll(userId: number, enabled = true) {
  return useQuery({
    queryKey: payrollKeys.person(userId),
    queryFn: async () =>
      (await api.get<PersonPayroll>(`/api/hr/payroll/people/${userId}`)).data,
    enabled: enabled && Number.isFinite(userId) && userId > 0,
  });
}

export function useBonusRules(enabled = true) {
  return useQuery({
    queryKey: payrollKeys.rules,
    queryFn: async () => (await api.get<BonusRules>("/api/hr/payroll/rules")).data,
    enabled,
  });
}

function useInvalidatePayroll() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: payrollKeys.all });
}

/**
 * Zamknięcie miesiąca zakłada rozliczenia, ponowne otwarcie anuluje nieopłacone —
 * odświeżamy też rozliczenia i przelewy („Dla Finansów”, podgląd Symfonii), żeby
 * zakładki miesiąca nie pokazywały stanu sprzed decyzji (audyt A2, 19.10.2026).
 */
function useInvalidatePayrollPeriod() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: payrollKeys.all }),
      queryClient.invalidateQueries({ queryKey: settlementKeys.all }),
      queryClient.invalidateQueries({ queryKey: paymentKeys.all }),
    ]);
}

export function useSetRate(userId: number) {
  const invalidate = useInvalidatePayroll();
  return useMutation({
    mutationFn: async (input: RateInput) =>
      (await api.post<RateRow>(`/api/hr/payroll/people/${userId}/rates`, input)).data,
    onSuccess: invalidate,
  });
}

export function useDeleteRate() {
  const invalidate = useInvalidatePayroll();
  return useMutation({
    mutationFn: async (rateId: number) => {
      await api.delete(`/api/hr/payroll/rates/${rateId}`);
    },
    onSuccess: invalidate,
  });
}

export type SettlementRowStatus =
  | "matches"
  | "differs"
  | "zero"
  | "inactive"
  | "no_contract"
  | "no_placement"
  | "no_person"
  | "self"
  | "already_assigned";

export interface SettlementImportRow {
  index: number;
  person: string;
  candidate: string;
  amount: string;
  note: string;
  recipient_user_id: number | null;
  recipient_name: string | null;
  recipient_active: boolean | null;
  contract_id: number | null;
  contract_label: string | null;
  start_date: string | null;
  role: string | null;
  keyed: boolean;
  category: BonusCategory;
  automat_name: string | null;
  automat_amount: string | null;
  selected: boolean;
  status: SettlementRowStatus;
}

export interface SettlementImportPreview {
  year: number;
  month: number;
  rows: SettlementImportRow[];
  counts: Partial<Record<SettlementRowStatus, number>>;
  total: string;
}

/** Porównanie arkusza z NEXUSEM. Nic nie zapisuje, plik zostaje w przeglądarce. */
export function useSettlementImportPreview(year: number, month: number) {
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return (
        await api.post<SettlementImportPreview>(
          `/api/hr/payroll/months/${year}/${month}/settlement-import/preview`,
          form,
          { headers: { "Content-Type": "multipart/form-data" } },
        )
      ).data;
    },
  });
}

export function useApplySettlementImport(year: number, month: number) {
  const invalidate = useInvalidatePayroll();
  return useMutation({
    mutationFn: async (rows: SettlementImportRow[]) =>
      (
        await api.post<{ assigned: number; rejected: number; skipped: number }>(
          `/api/hr/payroll/months/${year}/${month}/settlement-import`,
          { rows },
        )
      ).data,
    onSuccess: invalidate,
  });
}

export function useBonusDecisions(enabled: boolean) {
  return useQuery({
    queryKey: [...payrollKeys.all, "decisions"],
    queryFn: async () => (await api.get<BonusDecisions>("/api/hr/payroll/decisions")).data,
    enabled,
    staleTime: 60_000,
  });
}

export function useConfirmVoucher() {
  const invalidate = useInvalidatePayroll();
  return useMutation({
    mutationFn: async (id: number) =>
      (await api.post(`/api/hr/payroll/vouchers/${id}/confirm`)).data,
    onSuccess: invalidate,
  });
}

export function useContractBonuses(contractId: number, enabled: boolean) {
  return useQuery({
    queryKey: [...payrollKeys.all, "contract", contractId],
    queryFn: async () =>
      (await api.get<{ items: BonusRow[] }>(`/api/hr/payroll/contracts/${contractId}/bonuses`)).data
        .items,
    enabled,
  });
}

export function usePlacementOptions(enabled: boolean) {
  return useQuery({
    queryKey: [...payrollKeys.all, "placement-options"],
    queryFn: async () =>
      (await api.get<{ items: PlacementOption[] }>("/api/hr/payroll/placement-options")).data.items,
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useCreateBonus() {
  const invalidate = useInvalidatePayroll();
  return useMutation({
    mutationFn: async (input: BonusInput) =>
      (await api.post<BonusRow>("/api/hr/payroll/bonuses", input)).data,
    onSuccess: invalidate,
  });
}

export function useUpdateBonus() {
  const invalidate = useInvalidatePayroll();
  return useMutation({
    mutationFn: async ({ id, patch }: { id: number; patch: BonusPatch }) =>
      (await api.patch<BonusRow>(`/api/hr/payroll/bonuses/${id}`, patch)).data,
    onSuccess: invalidate,
  });
}

export function useApproveBonus() {
  const invalidate = useInvalidatePayroll();
  return useMutation({
    mutationFn: async (id: number) =>
      (await api.post<BonusRow>(`/api/hr/payroll/bonuses/${id}/approve`)).data,
    onSuccess: invalidate,
  });
}

/**
 * „Zatwierdź zaznaczone” (tylko Płace): wszystko albo nic — pierwsza odmowa
 * cofa całość, a komunikat mówi, przy czyjej premii
 * (`POST /api/hr/payroll/bonuses/approve-batch`).
 */
export function useApproveBonuses() {
  const invalidate = useInvalidatePayroll();
  return useMutation({
    mutationFn: async (ids: number[]) =>
      (
        await api.post<{ approved: number; items: BonusRow[] }>(
          "/api/hr/payroll/bonuses/approve-batch",
          { ids },
        )
      ).data,
    onSuccess: invalidate,
  });
}

export function useCancelBonus() {
  const invalidate = useInvalidatePayroll();
  return useMutation({
    mutationFn: async ({ id, note }: { id: number; note?: string | null }) =>
      (await api.post<BonusRow>(`/api/hr/payroll/bonuses/${id}/cancel`, { note: note ?? null }))
        .data,
    onSuccess: invalidate,
  });
}

export interface CloseResult {
  year: number;
  month: number;
  status: PeriodStatus;
  already_closed: boolean;
  people: number;
}

export function useCloseMonth(year: number, month: number) {
  const invalidate = useInvalidatePayrollPeriod();
  return useMutation({
    mutationFn: async (acknowledgeWarnings: boolean) =>
      (
        await api.post<CloseResult>(`/api/hr/payroll/months/${year}/${month}/close`, {
          acknowledge_warnings: acknowledgeWarnings,
        })
      ).data,
    onSuccess: invalidate,
  });
}

export function useReopenMonth(year: number, month: number) {
  const invalidate = useInvalidatePayrollPeriod();
  return useMutation({
    mutationFn: async (reason: string) =>
      (await api.post(`/api/hr/payroll/months/${year}/${month}/reopen`, { reason })).data,
    onSuccess: invalidate,
  });
}

export function useSaveBonusRules() {
  const invalidate = useInvalidatePayroll();
  return useMutation({
    mutationFn: async (rules: Partial<Omit<BonusRules, "currency">>) =>
      (await api.put<BonusRules>("/api/hr/payroll/rules", rules)).data,
    onSuccess: invalidate,
  });
}

/** Ustawienia → Płace: minimalne stawki na zleceniu (Płace, admin). */
export function useMinimumRates(enabled = true) {
  return useQuery({
    queryKey: payrollKeys.minimumRates,
    queryFn: async () =>
      (await api.get<MinimumRates>("/api/hr/payroll/settings/minimum-rates")).data,
    enabled,
  });
}

export function useSaveMinimumRates() {
  const invalidate = useInvalidatePayroll();
  return useMutation({
    mutationFn: async (rates: Record<string, string>) =>
      (await api.put<MinimumRates>("/api/hr/payroll/settings/minimum-rates", { rates })).data,
    onSuccess: invalidate,
  });
}

export function useRefreshProposals() {
  const invalidate = useInvalidatePayroll();
  return useMutation({
    mutationFn: async () =>
      (await api.post<Record<string, number>>("/api/hr/payroll/proposals/refresh")).data,
    onSuccess: invalidate,
  });
}

/** 409 przy zamykaniu miesiąca: kod i dane (ostrzeżenia albo liczba propozycji). */
export interface CloseConflict {
  code: "close_warnings" | "pending_bonuses" | "payroll_month_closed" | string;
  message: string;
  warnings: CloseWarning[];
  count: number;
}

export function closeConflict(error: unknown): CloseConflict | null {
  const response = (error as { response?: { status?: number; data?: unknown } } | null)
    ?.response;
  if (response?.status !== 409) return null;
  const detail = (response.data as { detail?: unknown } | undefined)?.detail;
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return null;
  const { code, message, warnings, count } = detail as {
    code?: unknown;
    message?: unknown;
    warnings?: unknown;
    count?: unknown;
  };
  if (typeof code !== "string") return null;
  return {
    code,
    message: typeof message === "string" ? message : "",
    warnings: Array.isArray(warnings) ? (warnings as CloseWarning[]) : [],
    count: typeof count === "number" ? count : 0,
  };
}
