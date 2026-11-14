// Lista płac liczona w NEXUSIE (K7a) — lista miesiąca, parametry, dane osób.
//
// Lustro `backend/app/api/hr_payroll_lists.py`. Moduł stoi za przełącznikiem
// `payroll` Księgowości (wyłączony = 404, administrator widzi). Kwoty, listy,
// parametry i pliki — uprawnienie „Rozliczenia” (`payroll`, admin zawsze, D2);
// dane osób — Administracja współpracy, Rozliczenia i admin. Kwoty przychodzą jako tekst dziesiętny w złotych
// („5646.86”); formatuje je `components/accounting/payroll/payroll-model.ts`.
// Kto zatwierdza listę, liczy serwer (`can_approve`, `approve_refusal`).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { downloadBlob, fetchAuthenticatedDownload } from "@/lib/authenticated-files";

const BASE = "/api/hr/payroll-lists";

export type PayrollKind = "uop" | "zlecenie" | "dzielo";
export type PayrollListStatus = "draft" | "approved" | "cancelled";

export interface PayrollProblem {
  code: string;
  label: string;
  blocking: boolean;
  /** Osoba, której problem dotyczy; brak = cała lista (np. parametry). */
  person?: string | null;
}

/** Skąd kwota pozycji: godziny i stawka, rozliczenie klienta, kwota Rozliczeń. */
export interface PayrollLineBasis {
  hours?: string | null;
  overtime_hours?: string | null;
  hourly_rate?: string | null;
  hours_amount?: string | null;
  bonus_total?: string | null;
  note?: string | null;
  settlement_status?: string | null;
  md_charged?: string | null;
  replaced_source?: string | null;
  replaced_gross?: string | null;
  /** Kwota Rozliczeń dla umowy zakończonej przed miesiącem. */
  outside_month?: boolean;
  missing_files?: string[] | null;
  [key: string]: unknown;
}

/** Wynik silnika: kwoty jako tekst (składki, podatek, PPK, pracodawca). */
export interface PayrollLineResult {
  tax_kind?: string;
  notes?: string[];
  [key: string]: unknown;
}

export interface PayrollLine {
  id: number;
  person_key: string;
  user_id: number | null;
  candidate_id: number | null;
  contract_id: number | null;
  person_name: string;
  kind: PayrollKind;
  kind_label: string;
  source: string;
  source_label: string;
  /** `null` = pozycja bez kwoty (np. brak rozliczenia klienta). */
  gross: string | null;
  net: string | null;
  pit: string | null;
  social_employee: string | null;
  health: string | null;
  employer_social: string | null;
  employer_cost: string | null;
  basis: PayrollLineBasis;
  result: PayrollLineResult;
  notes: { code: string; label: string }[];
  problems: PayrollProblem[];
  payee_last4: string | null;
}

export interface PayrollDeadlines {
  pay_date: string;
  zus: string;
  ppk: string;
  pit: string;
  /** Miesiąc deklaracji ZUS („RRRR-MM”) = miesiąc wypłaty. */
  declaration_month: string;
}

export interface PayrollTotals {
  people: number;
  lines: number;
  gross: string;
  net: string;
  social_employee: string;
  health: string;
  pit: string;
  pit_scale: string;
  pit_flat: string;
  employer_social: string;
  pension_employer: string;
  disability_employer: string;
  accident_employer: string;
  labour_fund: string;
  fgsp: string;
  zus_due: string;
  ppk_employee: string;
  ppk_employer: string;
  employer_cost: string;
  by_kind?: Partial<Record<PayrollKind, { lines: number; gross: string }>>;
  deadlines?: PayrollDeadlines;
}

export interface PayrollList {
  id: number;
  number: string;
  status: PayrollListStatus;
  year: number;
  month: number;
  pay_date: string;
  parameter_version: { id: number; effective_from: string; status: string; live: boolean } | null;
  totals: PayrollTotals;
  problems: PayrollProblem[];
  computed_by: string | null;
  computed_at: string | null;
  approved_by: string | null;
  approved_at: string | null;
  cancelled_by: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  transfers_created_at: string | null;
  paid_at: string | null;
  paid_by: string | null;
  can_approve: boolean;
  approve_refusal: string | null;
  lines: PayrollLine[];
}

/** Kwota brutto wpisana przez Rozliczenia na miesiąc (zastępuje źródło pozycji). */
export interface GrossInput {
  id: number;
  user_id: number | null;
  contract_id: number | null;
  kind: PayrollKind;
  gross: string;
  /** Podstawa do Funduszu Pracy w przeliczeniu na pełny miesiąc; brak = kwota brutto. */
  fund_basis: string | null;
  note: string;
  entered_at: string | null;
}

export interface PayrollMonth {
  year: number;
  month: number;
  /** Miesiąc w „Ludzie → Rozliczenia”: lista liczy się tylko z zamkniętego. */
  period_status: "open" | "closed";
  default_pay_date: string;
  can_compute: boolean;
  inputs: GrossInput[];
  cancelled: { id: number; number: string; cancelled_at: string | null; cancel_reason: string | null }[];
  list: PayrollList | null;
}

export interface GrossInputBody {
  user_id?: number;
  contract_id?: number;
  kind: PayrollKind;
  /** `null` usuwa wpis. */
  gross: string | null;
  /** Podstawa do Funduszu Pracy na pełny miesiąc; `null` = kwota brutto. */
  fund_basis?: string | null;
  note?: string;
}

export type TransferKind = "wage" | "zus" | "pit4" | "pit8ar";

export interface TransferRow {
  kind: TransferKind;
  line_id: number | null;
  name: string;
  amount: string;
  account_last4: string | null;
  included: boolean;
  reason: string | null;
}

export interface TransfersPlan {
  list_id: number;
  number: string;
  status: PayrollListStatus;
  rows: TransferRow[];
  transfers_created_at: string | null;
  paid_at: string | null;
}

export interface ParamCatalogItem {
  key: string;
  label: string;
  group: string;
  unit: string;
  min: string;
  max: string;
  integer: "0" | "1";
}

export interface ParamChange {
  key: string;
  label: string;
  unit: string;
  before: string;
  after: string;
}

export interface ParamVersion {
  id: number;
  effective_from: string;
  status: "to_confirm" | "confirmed";
  source: string;
  note: string | null;
  params: Record<string, string>;
  created_at: string | null;
  confirmed_at: string | null;
  replaced_at: string | null;
  live: boolean;
  in_use: boolean;
  changes: ParamChange[];
}

export interface PayrollCompany {
  nip: string;
  name: string;
  short_name: string;
  regon: string | null;
  tax_office_code: string | null;
  zus_account: string | null;
  tax_account: string | null;
  missing: string[];
}

export interface ParametersOverview {
  catalog: ParamCatalogItem[];
  current_id: number | null;
  versions: ParamVersion[];
  company?: PayrollCompany;
}

export interface CompanyInput {
  regon: string | null;
  short_name: string | null;
  tax_office_code: string | null;
  zus_account: string | null;
  tax_account: string | null;
}

export interface PayrollPersonRow {
  /** „u<id>” (konto) albo „c<id>” (kontraktor u klienta, kandydat). */
  subject: string;
  user_id: number | null;
  candidate_id: number | null;
  name: string;
  kind: string;
  exists: boolean;
  missing: string[];
  missing_labels: string[];
  pesel_masked: string | null;
  own: boolean;
}

/** Osoba z danymi płacowymi: konto z kartoteką albo kontraktor (kandydat). */
export type PersonSubject = { userId: number; candidateId?: undefined } | { candidateId: number; userId?: undefined };

export type AddressKey =
  | "country"
  | "voivodeship"
  | "county"
  | "commune"
  | "city"
  | "street"
  | "house_number"
  | "flat_number"
  | "postal_code"
  | "post_office";

export type PersonAddress = Partial<Record<AddressKey, string | null>>;

export type Relief = "family4" | "return" | "senior";

export interface PersonPpk {
  employee_rate: string;
  employee_extra?: string;
  employer_extra?: string;
}

/**
 * Dane kadrowo-płacowe z maskami: PESEL, numer dokumentu i rachunek nigdy nie
 * wracają w całości (pełne wartości idą tylko do plików KEDU, PIT i przelewów).
 */
export interface PersonData {
  subject: string;
  user_id: number | null;
  candidate_id: number | null;
  name: string;
  exists: boolean;
  can_edit: boolean;
  pesel_masked: string | null;
  document_type: "id_card" | "passport" | null;
  document_masked: string | null;
  /** Tylko wpisana ręcznie (bez PESEL-u). */
  birth_date: string | null;
  sex: "F" | "M" | null;
  /** NIP osoby bez PESEL-u (do PIT-11), 10 cyfr. */
  nip: string | null;
  first_name: string;
  last_name: string;
  /** Imię i nazwisko zapisane (inaczej to podpowiedź z konta). */
  names_confirmed: boolean;
  citizenship: string | null;
  address: PersonAddress | null;
  tax_office_code: string | null;
  tax_office_name: string | null;
  zus_title_code: string | null;
  /** Oddział NFZ („07R”): wpisany albo wyliczony z województwa adresu. */
  nfz_code: string | null;
  /** Wymiar etatu na umowie o pracę („1/1”, „1/2”); domyślnie pełny. */
  work_time: string;
  pit2: 0 | 12 | 24 | 36;
  kup: "standard" | "increased";
  reliefs: Relief[];
  youth_relief_waived: boolean;
  youth_relief_now: boolean;
  student_exempt_until: string | null;
  mandate: { pension_insurance: boolean; sickness_voluntary: boolean; accident_insurance: boolean };
  ppk: PersonPpk | null;
  labour_fund_exempt_until: string | null;
  fgsp_exempt_until: string | null;
  bank_account_last4: string | null;
  missing: string[];
  missing_labels: string[];
  blocks_calculation: string[];
  updated_at: string | null;
  version: number;
}

/** Zmiana danych osoby: tylko zmienione pola, `null` czyści pole. */
export interface PersonDataUpdate {
  expected_version: number;
  pesel?: string;
  document_type?: "id_card" | "passport" | null;
  document_number?: string;
  birth_date?: string | null;
  sex?: "F" | "M" | null;
  nip?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  citizenship?: string | null;
  address?: PersonAddress | null;
  tax_office_code?: string | null;
  tax_office_name?: string | null;
  zus_title_code?: string | null;
  /** 01R–16R; `null` = z województwa adresu. */
  nfz_code?: string | null;
  /** „1/2”; „1/1” albo `null` = pełny etat. */
  work_time?: string | null;
  pit2?: 0 | 12 | 24 | 36;
  kup?: "standard" | "increased";
  reliefs?: Relief[];
  youth_relief_waived?: boolean;
  student_exempt_until?: string | null;
  mandate_pension_insurance?: boolean;
  mandate_sickness_voluntary?: boolean;
  mandate_accident_insurance?: boolean;
  ppk?: { participates: boolean; employee_rate?: string; employee_extra?: string; employer_extra?: string };
  labour_fund_exempt_until?: string | null;
  fgsp_exempt_until?: string | null;
  bank_account?: string;
}

export type RegistrationKind = "ZUA" | "ZZA" | "ZWUA";

/** Zgłoszenie albo wyrejestrowanie osoby w ZUS w zakresie dat. */
export interface RegistrationEvent {
  kind: RegistrationKind;
  person_key: string;
  user_id: number | null;
  candidate_id: number | null;
  contract_id: number | null;
  name: string;
  title_kind: "uop" | "zlecenie";
  on: string;
  problems: { code: string; label: string }[];
}

export interface Registrations {
  date_from: string;
  date_to: string;
  events: RegistrationEvent[];
  skipped: { name: string; kind: string; reason: string }[];
  /** Jest co najmniej jedno zgłoszenie z kompletem danych do pliku KEDU. */
  file_available: boolean;
}

/** Kto ma komplet danych do PIT-11 za rok (ZIP bierze tylko gotowych). */
export interface Pit11Overview {
  year: number;
  people: { person_key: string; name: string; ready: boolean; missing: string[] }[];
}

export const payrollListKeys = {
  all: ["payroll-lists"] as const,
  months: ["payroll-lists", "month"] as const,
  month: (year: number, month: number) => ["payroll-lists", "month", year, month] as const,
  transfers: (listId: number) => ["payroll-lists", "transfers", listId] as const,
  parameters: ["payroll-lists", "parameters"] as const,
  people: ["payroll-lists", "people"] as const,
  person: (subject: string) => ["payroll-lists", "person", subject] as const,
  registrations: (dateFrom: string, dateTo: string) => ["payroll-lists", "registrations", dateFrom, dateTo] as const,
  pit11: (year: number) => ["payroll-lists", "pit-11", year] as const,
};

/** „u12” / „c34” — ten sam klucz co `subject` z API. */
export function subjectKey(subject: PersonSubject): string {
  return subject.userId != null ? `u${subject.userId}` : `c${subject.candidateId}`;
}

function subjectPath(subject: PersonSubject): string {
  return subject.userId != null
    ? `${BASE}/people/users/${subject.userId}`
    : `${BASE}/people/candidates/${subject.candidateId}`;
}

export type YearFile = "pit-4r.xml" | "pit-4r.pdf" | "pit-8ar.xml" | "pit-8ar.pdf" | "pit-11.zip";

/** Ścieżki plików (pobranie z sesją przez `downloadPayrollFile`). */
export const payrollPaths = {
  payslips: (listId: number, lineId?: number) =>
    `${BASE}/lists/${listId}/payslips.pdf${lineId != null ? `?line_id=${lineId}` : ""}`,
  /** KEDU (DRA + RCA) za miesiąc deklaracji „RRRR-MM”. */
  kedu: (declarationMonth: string) => {
    const [year, month] = declarationMonth.split("-").map(Number);
    return `${BASE}/declarations/${year}/${month}/kedu.xml`;
  },
  year: (year: number, file: YearFile) => `${BASE}/years/${year}/${file}`,
  transfersFile: (listId: number) => `${BASE}/lists/${listId}/transfers/file`,
  /** KEDU ze zgłoszeniami ZUA, ZZA i ZWUA w zakresie dat. */
  registrations: (dateFrom: string, dateTo: string) =>
    `${BASE}/registrations.xml?date_from=${dateFrom}&date_to=${dateTo}`,
};

/** Pobiera plik z sesją; nazwa z nagłówka serwera, inaczej `fallbackName`. */
export async function downloadPayrollFile(
  path: string,
  fallbackName: string,
  method: "GET" | "POST" = "GET",
): Promise<void> {
  const file = await fetchAuthenticatedDownload(path, method === "POST" ? { method: "POST", body: {} } : undefined);
  downloadBlob(file.blob, file.filename ?? fallbackName);
}

export function usePayrollMonth(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: payrollListKeys.month(year, month),
    queryFn: async () => (await api.get<PayrollMonth>(`${BASE}/months/${year}/${month}`)).data,
    enabled,
  });
}

/**
 * Akcje listy odpowiadają stanem miesiąca — wpisuje się go wprost do pamięci
 * zapytań. Błąd (lista nieaktualna, zablokowana, okres otwarty) odświeża
 * miesiąc, żeby ekran pokazał to, na co serwer odmówił.
 */
function useMonthMutation<TArgs>(request: (args: TArgs) => Promise<PayrollMonth>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: (data) => {
      client.setQueryData(payrollListKeys.month(data.year, data.month), data);
      client.invalidateQueries({ queryKey: ["payroll-lists", "transfers"] });
    },
    onError: () => client.invalidateQueries({ queryKey: payrollListKeys.months }),
  });
}

export function useComputeList() {
  return useMonthMutation(
    async (args: { year: number; month: number; payDate?: string | null }) =>
      (
        await api.post<PayrollMonth>(`${BASE}/months/${args.year}/${args.month}/compute`, {
          pay_date: args.payDate || undefined,
        })
      ).data,
  );
}

export function useSetGrossInput() {
  return useMonthMutation(
    async (args: { year: number; month: number; body: GrossInputBody }) =>
      (await api.put<PayrollMonth>(`${BASE}/months/${args.year}/${args.month}/inputs`, args.body)).data,
  );
}

export function useApproveList() {
  return useMonthMutation(
    async (listId: number) => (await api.post<PayrollMonth>(`${BASE}/lists/${listId}/approve`)).data,
  );
}

export function useCancelList() {
  return useMonthMutation(
    async (args: { listId: number; reason: string }) =>
      (await api.post<PayrollMonth>(`${BASE}/lists/${args.listId}/cancel`, { reason: args.reason })).data,
  );
}

export function useMarkPaid() {
  return useMonthMutation(
    async (listId: number) => (await api.post<PayrollMonth>(`${BASE}/lists/${listId}/paid`)).data,
  );
}

export function useTransfersPlan(listId: number | null, enabled = true) {
  return useQuery({
    queryKey: payrollListKeys.transfers(listId ?? 0),
    queryFn: async () => (await api.get<TransfersPlan>(`${BASE}/lists/${listId}/transfers`)).data,
    enabled: enabled && listId != null,
  });
}

/** Plik przelewów (Elixir-O albo CSV); pierwsze pobranie zapisuje datę na liście. */
export function useTransfersFile() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (args: { listId: number; fallbackName: string }) =>
      downloadPayrollFile(payrollPaths.transfersFile(args.listId), args.fallbackName, "POST"),
    onSettled: () => {
      client.invalidateQueries({ queryKey: payrollListKeys.months });
      client.invalidateQueries({ queryKey: ["payroll-lists", "transfers"] });
    },
  });
}

export function usePayrollParameters(enabled = true) {
  return useQuery({
    queryKey: payrollListKeys.parameters,
    queryFn: async () => (await api.get<ParametersOverview>(`${BASE}/parameters`)).data,
    enabled,
  });
}

/**
 * Zapis, potwierdzenie i wycofanie wersji odpowiadają historią bez danych
 * płatnika — te zostają z poprzedniego odczytu. Lista miesiąca zna wersję
 * parametrów, więc też się odświeża.
 */
function useParametersMutation<TArgs>(request: (args: TArgs) => Promise<ParametersOverview>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: (data) => {
      client.setQueryData<ParametersOverview>(payrollListKeys.parameters, (current) => ({
        ...data,
        company: data.company ?? current?.company,
      }));
      client.invalidateQueries({ queryKey: payrollListKeys.months });
    },
  });
}

export function useSaveParameters() {
  return useParametersMutation(
    async (body: { effective_from: string; params: Record<string, string>; note?: string | null }) =>
      (await api.post<ParametersOverview>(`${BASE}/parameters`, body)).data,
  );
}

export function useConfirmParameters() {
  return useParametersMutation(
    async (versionId: number) => (await api.post<ParametersOverview>(`${BASE}/parameters/${versionId}/confirm`)).data,
  );
}

export function useWithdrawParameters() {
  return useParametersMutation(
    async (versionId: number) => (await api.post<ParametersOverview>(`${BASE}/parameters/${versionId}/withdraw`)).data,
  );
}

export function useSaveCompany() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: CompanyInput) => (await api.put<PayrollCompany>(`${BASE}/company`, body)).data,
    onSuccess: (company) =>
      client.setQueryData<ParametersOverview>(payrollListKeys.parameters, (current) =>
        current ? { ...current, company } : current,
      ),
  });
}

export function useRegistrations(dateFrom: string, dateTo: string, enabled = true) {
  return useQuery({
    queryKey: payrollListKeys.registrations(dateFrom, dateTo),
    queryFn: async () =>
      (
        await api.get<Registrations>(`${BASE}/registrations`, {
          params: { date_from: dateFrom, date_to: dateTo },
        })
      ).data,
    enabled,
  });
}

export function usePit11(year: number, enabled = true) {
  return useQuery({
    queryKey: payrollListKeys.pit11(year),
    queryFn: async () => (await api.get<Pit11Overview>(`${BASE}/years/${year}/pit-11`)).data,
    enabled,
  });
}

export function usePayrollPeople(enabled = true) {
  return useQuery({
    queryKey: payrollListKeys.people,
    queryFn: async () => (await api.get<{ people: PayrollPersonRow[] }>(`${BASE}/people`)).data.people,
    enabled,
  });
}

export function usePersonData(subject: PersonSubject | null, enabled = true) {
  return useQuery({
    queryKey: payrollListKeys.person(subject ? subjectKey(subject) : ""),
    queryFn: async () => (await api.get<PersonData>(subjectPath(subject as PersonSubject))).data,
    enabled: enabled && subject != null,
  });
}

export function useSavePersonData(subject: PersonSubject) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: PersonDataUpdate) => (await api.put<PersonData>(subjectPath(subject), body)).data,
    onSuccess: (data) => {
      client.setQueryData(payrollListKeys.person(subjectKey(subject)), data);
      client.invalidateQueries({ queryKey: payrollListKeys.people });
    },
  });
}
