// „Ludzie w NEXUSIE” (16.10.2026) — Płace i premie.
//
// Lustro `backend/app/api/hr_payroll.py`. Zakres liczy serwer (D2): Płace widzą
// stawki i kwoty wszystkich, osoba swoje, przełożony godziny i premie zespołu
// bez stawek — odpowiedź dla przełożonego po prostu nie ma tych pól. Kwoty
// przychodzą jako tekst dziesiętny ("1234.50"); formatuje je `payroll-format.ts`.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { EmploymentType } from "@/lib/api/hr";
import { downloadBlob, fetchAuthenticatedDownload } from "@/lib/authenticated-files";

export type Currency = "PLN" | "EUR" | "USD";
export type BonusCategory = "sales" | "delivery_lead" | "recruiter" | "custom" | "league";
export type BonusStatus = "proposed" | "assigned" | "cancelled";
export type BonusSource = "manual" | "contract_placement" | "league" | "compass_import";
export type TimesheetStatus = "draft" | "submitted" | "approved";
export type PeriodStatus = "open" | "closed";

export interface RateRow {
  id: number;
  user_id: number;
  hourly_rate: string;
  currency: Currency;
  effective_from: string;
  effective_to: string | null;
  reason: string | null;
  set_by: number | null;
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
  assigned_at: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  /** Kwota propozycji automatu poprawiona ręcznie. */
  edited: boolean;
  /** Tylko dla Płac: reguły i liczby, z których wyszła kwota. */
  rule_snapshot?: Record<string, unknown>;
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
  totals?: Record<string, string>;
  warnings?: CloseWarning[];
}

export interface MyPayroll {
  current_rate: RateRow | null;
  rates: RateRow[];
  bonuses: BonusRow[];
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

export interface BonusRules {
  recruiter_tier_bounds: [string, string];
  recruiter_tier_amounts: [string, string, string];
  dl_percent: string;
  monthly_hours: number;
  eligible_business_days: number;
  currency: Currency;
  extra_dl: ExtraDlRule[];
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
}

export type BonusPatch = Partial<Omit<BonusInput, "recipient_user_id">>;

export const payrollKeys = {
  all: ["hr-payroll"] as const,
  me: ["hr-payroll", "me"] as const,
  months: ["hr-payroll", "months"] as const,
  month: (year: number, month: number) => ["hr-payroll", "month", year, month] as const,
  person: (userId: number) => ["hr-payroll", "person", userId] as const,
  rules: ["hr-payroll", "rules"] as const,
};

export const payrollPaths = {
  export: (year: number, month: number) =>
    `/api/hr/payroll/months/${year}/${month}/export.xlsx`,
  /** Paczka PDF-ów zatwierdzonych timesheetów (moduł czasu, `hr_time.py`). */
  timesheetsZip: (year: number, month: number) =>
    `/api/hr/time/export/${year}/${month}/zip`,
};

export function useMyPayroll(enabled = true) {
  return useQuery({
    queryKey: payrollKeys.me,
    queryFn: async () => (await api.get<MyPayroll>("/api/hr/payroll/me")).data,
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
  const invalidate = useInvalidatePayroll();
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
  const invalidate = useInvalidatePayroll();
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

export function useRefreshProposals() {
  const invalidate = useInvalidatePayroll();
  return useMutation({
    mutationFn: async () =>
      (await api.post<Record<string, number>>("/api/hr/payroll/proposals/refresh")).data,
    onSuccess: invalidate,
  });
}

/** Pobiera plik (XLSX/ZIP) z tokenem i zapisuje pod nazwą z serwera. */
export async function downloadPayrollFile(path: string, fallbackName: string): Promise<void> {
  const { blob, filename } = await fetchAuthenticatedDownload(path);
  downloadBlob(blob, filename ?? fallbackName);
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
