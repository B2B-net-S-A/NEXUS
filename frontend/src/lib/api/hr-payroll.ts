// „Ludzie w NEXUSIE” (16.10.2026) — Płace i premie.
//
// Lustro `backend/app/api/hr_payroll.py`. Zakres liczy serwer (D2): Płace widzą
// stawki i kwoty wszystkich, osoba swoje, przełożony godziny i premie zespołu
// bez stawek — odpowiedź dla przełożonego po prostu nie ma tych pól. Kwoty
// przychodzą jako tekst dziesiętny ("1234.50"); formatuje je `payroll-format.ts`.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type B2BReplaceableContract } from "@/lib/api";
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
  /** `amount_rule`: kwota z reguły do porównania z kwotą z arkusza. */
  rule_amount?: string;
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
  /** Wiersz z arkusza Delivery: kwota i osoba przyszły z pliku, nie z reguły. */
  from_sheet?: boolean;
  /** Premia 200%: miesiąc podpisu „RRRR-MM”, w którym osoba zrobiła cel. */
  double_bonus_month?: string | null;
  /** Anulowana przez automat: dzień końca kontraktu. */
  cancel_ended_on?: string | null;
  /** Widok miesiąca: przyznana premia z placementu, a kontrakt skończył się przed terminem. */
  contract_ended_early?: boolean;
  /** Osoba zmieniona ręcznie przez Płace (automat jej nie nadpisuje). */
  edited_recipient?: boolean;
  flags?: BonusFlag[];
  /** Płace, premia z placementu: dzień podpisu umowy do „Popraw datę podpisu”. */
  signature?: Omit<DoubleBonusContract, "label"> | null;
  stages?: BonusStageFacts;
  /** Tylko dla Płac: reguły i liczby, z których wyszła kwota. */
  rule_snapshot?: Record<string, unknown>;
  /** Listy Płac: czy widz może zatwierdzić propozycję (ręczną przełożonego — tylko Płace). */
  can_approve?: boolean;
  /** Gwarancja premii DL: premia ma dług do zwrotu (otwarty albo spłacony). */
  has_clawback?: boolean;
  /** Płace: „Zwrot z gwarancji” — przyznana premia DL bez długu, nie własna. */
  can_clawback?: boolean;
  /** Propozycje „liczy się”: postęp do terminu. */
  business_days_elapsed?: number | null;
  business_days_required?: number;
}

export interface PayrollLine {
  currency: Currency;
  hourly_rate: string | null;
  hours_amount: string | null;
  /** Premie po potrąceniu z gwarancji; przed potrąceniem = `bonus_total + clawback_total`. */
  bonus_total: string;
  /** Potrącenie z gwarancji premii DL (0653); brak = linia sprzed gwarancji. */
  clawback_total?: string;
  total: string;
}

/**
 * Dług z gwarancji premii DL (05.11.2026): konsultant nie przepracował 12 miesięcy
 * od startu kontraktu, więc DL oddaje całą premię — potrąca się sama z kolejnych.
 */
export interface BonusClawback {
  id: number;
  bonus_id: number;
  recipient_user_id: number;
  recipient_name: string | null;
  contract_id: number | null;
  description: string | null;
  /** Miesiąc wypłaty premii, `RRRR-MM`. */
  bonus_period: string;
  amount: string;
  currency: Currency;
  /** Potrącone w zamkniętych miesiącach. */
  settled: string;
  remaining: string;
  /** Dług anulowany po potrąceniu (np. cofnięty koniec kontraktu): do oddania premią. */
  refund_due: string | null;
  origin: "automatic" | "manual";
  status: "open" | "settled" | "cancelled";
  contract_start: string | null;
  ended_on: string | null;
  /** Pierwszy dzień miesiąca, od którego dług bierze premie („z kolejnych premii”). */
  deduct_from: string;
  guarantee_until: string | null;
  note: string | null;
  cancel_reason: string | null;
  created_at: string | null;
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
  /** Moje długi z gwarancji premii DL. */
  clawbacks?: BonusClawback[];
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
  /** Pusta lista = każdy klient. */
  client_ids?: number[];
  client_names?: string[];
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

/** Pozycja poza regułami wpisana przez admina: automat ją przyznaje. */
export interface BonusRuleItem {
  user_id: number;
  amount: string;
  month: string;
  reason: string;
}

export interface BonusRules {
  recruiter_tier_bounds: [string, string];
  recruiter_tier_amounts: [string, string, string];
  dl_percent: string;
  monthly_hours: number;
  /** Godziny premii każdego DL-a; `null` = `monthly_hours`. Wyjątki w `dl_hours`. */
  dl_default_hours?: number | null;
  /** Miesiąc RRRR-MM: od niego automat przyznaje sam, a ręcznie zmienia tylko admin. */
  auto_assign_from?: string | null;
  rule_items?: BonusRuleItem[];
  eligible_business_days: number;
  currency: Currency;
  extra_dl: ExtraDlRule[];
  /** Klienci z przypisanym Delivery Leadem, do zakresu dodatkowej premii. */
  client_options?: { id: number; name: string }[];
  dl_hours?: DlHoursRule[];
  individual_recruiters?: IndividualRecruiterRule[];
  automation_since: string | null;
  league_types: string[];
  /** Stała premia rekrutera dla roli głównej (np. TCM 1000 zł) zamiast progów marży. */
  fixed_role_amounts?: FixedRoleAmount[];
  /** Premia 200% w wybranych miesiącach; `null` = wyłączona. */
  double_bonus?: DoubleBonusRule | null;
}

export interface FixedRoleAmount {
  role: string;
  amount: string;
}

export interface DoubleBonusRule {
  /** „RRRR-MM”. */
  months: string[];
  verifications_per_day: string;
  precision_pct: string;
  dl_min_margin: string;
}

/**
 * Skąd jest dzień podpisu (06.11.2026): `pdf` — podpis konsultanta w pliku,
 * `manual` — wpisany ręcznie z powodem (podpis odręczny albo poprawka Płac),
 * `esign` — podpis kontraktora w NEXUSIE, `signed` — oznaczenie sprzed tej
 * zmiany (data z okna), `created` — dzień założenia kontraktu bez Generatora.
 */
export type DoubleBonusSignedSource = "pdf" | "manual" | "esign" | "signed" | "created";

/** Umowa, z której jest dzień podpisu (tylko Płace). */
export interface DoubleBonusAgreement {
  generated_contract_id: number;
  contract_number: string | null;
  signed_on_source: "pdf" | "manual" | "esign" | null;
  signed_on_reason: string | null;
  set_by_name: string | null;
  marked_by_name: string | null;
  marked_at: string | null;
  consultant_signed_at: string | null;
  has_signed_file: boolean;
}

export interface DoubleBonusContract {
  contract_id: number;
  label: string;
  signed_on: string;
  signed_source: DoubleBonusSignedSource;
  /** Tylko Płace; „Moja współpraca” dostaje kontrakty bez marży. */
  margin_per_hour?: string | null;
  /** Tylko Płace; `null` = kontrakt bez umowy z Generatora. */
  agreement?: DoubleBonusAgreement | null;
}

export interface SignedOnCorrection {
  generated_contract_id: number;
  contract_id: number;
  signed_on: string;
  previous_signed_on: string | null;
  /** Miesiące programu z zapisanym wynikiem do przeliczenia (`RRRR-MM`). */
  settle_months: string[];
}

export interface DoubleBonusRecruiter {
  user_id: number;
  name: string | null;
  kind: "recruiter";
  placements: number;
  target: number | null;
  verifications_per_day: string | null;
  precision_pct: string | null;
  checks: { placements: boolean; verifications: boolean; precision: boolean };
  excluded: "inactive" | "individual" | "fixed_role" | null;
  qualified: boolean;
  /** Po zapisie wyniku: decyzja (może różnić się od stanu na dziś). */
  decided?: boolean;
  contracts: DoubleBonusContract[];
}

export interface DoubleBonusDl {
  user_id: number;
  name: string | null;
  kind: "dl";
  placements: number;
  average_margin: string | null;
  missing_margins: number;
  excluded: "inactive" | null;
  qualified: boolean;
  /** Po zapisie wyniku: decyzja (może różnić się od stanu na dziś). */
  decided?: boolean;
  contracts: DoubleBonusContract[];
}

export interface DoubleBonusThresholds {
  verifications_per_day: string;
  precision_pct: string;
  dl_min_margin: string;
  multiplier: string;
}

export interface DoubleBonusMonth {
  year: number;
  month: number;
  in_program: boolean;
  /** Miesiąc się skończył: wynik jest decyzją, nie postępem. */
  final: boolean;
  thresholds?: DoubleBonusThresholds;
  recruiters: DoubleBonusRecruiter[];
  dls: DoubleBonusDl[];
  /** Zapisana decyzja (kto dostaje 200%) — po końcu miesiąca. */
  stored: {
    recruiters: number[];
    dls: number[];
    recruiter_contracts?: Record<string, number>;
    dl_contracts?: Record<string, number>;
    computed_at: string;
  } | null;
}

export interface MyDoubleBonus {
  year: number;
  month: number;
  in_program: boolean;
  final: boolean;
  thresholds?: DoubleBonusThresholds | null;
  rows: (DoubleBonusRecruiter | DoubleBonusDl)[];
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
  clawbacks: ["hr", "payroll", "clawbacks"] as const,
  bonusMode: ["hr", "payroll", "bonus-mode"] as const,
  minimumRates: ["hr", "payroll", "minimum-rates"] as const,
  doubleBonus: (year: number, month: number) =>
    ["hr", "payroll", "double-bonus", year, month] as const,
  myDoubleBonus: ["hr", "payroll", "me", "double-bonus"] as const,
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

/** „Do 200%”: postęp osoby w bieżącym miesiącu programu. */
export function useMyDoubleBonus(enabled = true) {
  return useQuery({
    queryKey: payrollKeys.myDoubleBonus,
    queryFn: async () =>
      (await api.get<MyDoubleBonus>("/api/hr/payroll/me/double-bonus")).data,
    enabled,
  });
}

/** Płace: kto zrobił cel 200% w miesiącu (w trakcie miesiąca — postęp). */
export function useDoubleBonusMonth(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: payrollKeys.doubleBonus(year, month),
    queryFn: async () =>
      (await api.get<DoubleBonusMonth>(`/api/hr/payroll/double-bonus/${year}/${month}`))
        .data,
    enabled: enabled && Number.isFinite(year) && Number.isFinite(month),
  });
}

export function useSettleDoubleBonus(year: number, month: number) {
  const invalidate = useInvalidatePayroll();
  return useMutation({
    mutationFn: async () =>
      (
        await api.post<DoubleBonusMonth>(
          `/api/hr/payroll/double-bonus/${year}/${month}/settle`,
        )
      ).data,
    onSuccess: invalidate,
  });
}

/** Płace poprawiają dzień podpisu umowy z powodem (ślad w historii umowy). */
export function useCorrectSignedOn() {
  const invalidate = useInvalidatePayroll();
  return useMutation({
    mutationFn: async (input: {
      generatedContractId: number;
      signedOn: string;
      reason: string;
    }) =>
      (
        await api.post<SignedOnCorrection>(
          `/api/hr/payroll/double-bonus/agreements/${input.generatedContractId}/signed-on`,
          { signed_on: input.signedOn, reason: input.reason },
        )
      ).data,
    onSuccess: invalidate,
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

/**
 * „Szczegóły administracyjne” podpisanego kontraktu (06.11.2026): replacement,
 * „za kogo” i kandydat wskazany przez klienta. Od nich zależą premie z placementu.
 */
export interface ContractAdminDetails {
  contract_id: number;
  candidate_id: number | null;
  client_id: number | null;
  is_replacement: boolean | null;
  replaced_contract_id: number | null;
  replaced: B2BReplaceableContract | null;
  is_client_referral: boolean | null;
}

export interface ContractAdminDetailsInput {
  is_replacement: boolean | null;
  replaced_contract_id: number | null;
  is_client_referral: boolean | null;
  reason: string;
}

export function useContractAdminDetails(contractId: number, enabled: boolean) {
  return useQuery({
    queryKey: [...payrollKeys.all, "contract-admin", contractId],
    queryFn: async () =>
      (
        await api.get<ContractAdminDetails>(
          `/api/hr/payroll/contracts/${contractId}/admin-details`,
        )
      ).data,
    enabled,
  });
}

export function useSaveContractAdminDetails(contractId: number) {
  const invalidate = useInvalidatePayroll();
  return useMutation({
    mutationFn: async (input: ContractAdminDetailsInput) =>
      (
        await api.put<ContractAdminDetails & { changed: string[] }>(
          `/api/hr/payroll/contracts/${contractId}/admin-details`,
          input,
        )
      ).data,
    // Premie kontraktu przelicza serwer — odświeżamy też „Premie z tego kontraktu”.
    onSuccess: invalidate,
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

/** Czy premie przyznaje automat i czy ta osoba może zmieniać je ręcznie (09.11.2026). */
export function useBonusMode() {
  return useQuery({
    queryKey: payrollKeys.bonusMode,
    queryFn: async () =>
      (await api.get<{ automatic: boolean; manual_allowed: boolean }>("/api/hr/payroll/bonus-mode"))
        .data,
    staleTime: 60_000,
  });
}

export function useReportBonus() {
  return useMutation({
    mutationFn: async ({ id, note }: { id: number; note: string }) => {
      await api.post(`/api/hr/payroll/bonuses/${id}/report`, { note });
    },
  });
}

/** Płace: długi z gwarancji premii DL (otwarte, spłacone, do oddania). */
export function useBonusClawbacks(enabled = true) {
  return useQuery({
    queryKey: payrollKeys.clawbacks,
    queryFn: async () =>
      (await api.get<{ items: BonusClawback[] }>("/api/hr/payroll/clawbacks")).data.items,
    enabled,
  });
}

export function useRegisterClawback() {
  const invalidate = useInvalidatePayroll();
  return useMutation({
    mutationFn: async ({ bonusId, note }: { bonusId: number; note: string }) =>
      (await api.post<BonusClawback>(`/api/hr/payroll/bonuses/${bonusId}/clawback`, { note }))
        .data,
    onSuccess: invalidate,
  });
}

export function useCancelClawback() {
  const invalidate = useInvalidatePayroll();
  return useMutation({
    mutationFn: async ({ id, note }: { id: number; note: string }) =>
      (await api.post<BonusClawback>(`/api/hr/payroll/clawbacks/${id}/cancel`, { note })).data,
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
