// „Ludzie w NEXUSIE” (16.10.2026) — katalog ludzi, kartoteka, Kadry.
//
// Lustro `backend/app/api/hr_people.py` i `backend/app/api/hr_admin.py`.
// Zakres widoczności liczy serwer (`scope`: wizytówka albo pełna kartoteka);
// front pokazuje to, co dostał. Stawek i kwot tu nie ma (moduł Płace).

import { useEffect, useRef } from "react";
import {
  useIsMutating,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api } from "@/lib/api";
import { downloadBlob, fetchAuthenticatedDownload } from "@/lib/authenticated-files";
import { EMPLOYMENT_TERMS } from "@/lib/hr-employment-terms";

export type HrModuleKey =
  | "people"
  | "leave"
  | "time"
  | "payroll"
  | "lifecycle"
  | "care"
  | "cases"
  | "equipment"
  | "settlements"
  | "approvals";

export type EmploymentType = "uop" | "b2b" | "zlecenie";
export type EmploymentStatus =
  "pending" | "onboarding" | "active" | "offboarding" | "exited";
export type WorkLocation = "onsite" | "remote";
/** Pion firmy (17.10.2026): Front office — do podpisania zamówienia, Back office — po. */
export type Division = "front_office" | "back_office";

export interface HrConfig {
  /**
   * Główny wyłącznik programu (`HR_PROGRAM_ENABLED`, Artur 18.10.2026).
   * `false` = nic z „Ludzi w NEXUSIE” nie jest widoczne, także dla admina.
   */
  program: boolean;
  modules: Record<HrModuleKey, boolean>;
  /** Moduły otwarte dla tej osoby (admin widzi wszystkie). */
  open_modules: Record<HrModuleKey, boolean>;
  me: {
    has_profile: boolean;
    employment_status: EmploymentStatus | null;
    is_manager: boolean;
    direct_reports: number;
    is_admin: boolean;
    people_admin: boolean;
    payroll: boolean;
    equipment: boolean;
    cases: boolean;
    /** „Raporty godzin”: akceptuje timesheety całej firmy (28.10.2026). */
    timesheets?: boolean;
    /** Widzi kolejkę nieobecności (ta sama reguła co bramka tras urlopów). */
    leave_approver?: boolean;
    /** Przypisany do sprawy administracja@ (bez uprawnienia widzi tylko swoje). */
    has_assigned_cases?: boolean;
    /** Head back office — edytuje ścieżkę wejścia „Konsultant u klienta” (O4). */
    back_office_head?: boolean;
    /** Kogo osoba zastępuje dziś (przełożony na urlopie z nią jako zastępcą). */
    covering?: { manager_user_id: number; manager_name: string; until: string; reports: number }[];
  };
}

export interface PersonToday {
  absent_until: string | null;
  half_day: "morning" | "afternoon" | null;
  substitute_name: string | null;
  presence: "remote" | "business_trip" | null;
}

export interface PersonCard {
  user_id: number;
  name: string;
  email: string;
  job_title: string | null;
  department: string | null;
  phone: string | null;
  default_location: WorkLocation;
  employment_status: EmploymentStatus;
  manager_user_id: number | null;
  manager_name: string | null;
  scope: "card" | "full";
  /**
   * Kolumna „Dziś” katalogu (`GET /api/hr/people`, 19.10.2026): nieobecność
   * bez rodzaju (D6), praca zdalna i delegacja. `null` = nic szczególnego;
   * brak klucza = trasa bez kolumny (kartoteka pojedynczej osoby).
   */
  today?: PersonToday | null;
}

export interface LeaveEntitlementRow {
  year: number;
  entitlement_days: string | null;
  carried_over_days: string;
  used_initial_days: string;
  /** Odpowiedź zapisu: podpowiedź wymiaru 20/26 z kartoteki (D9). */
  suggested_entitlement_days?: number | null;
}

export interface LeaveRing {
  year: number;
  has_paid_pool: boolean;
  entitlement_days: string | null;
  carried_over_days: string | null;
  used_days: string | null;
  planned_days: string | null;
  remaining_days: string | null;
}

export interface PersonFull extends PersonCard {
  /**
   * Forma umowy — `null`: ukryta (widzą ją tylko osoba, jej przełożony, admin
   * i Finanse — `people.form_viewer`, 19.10.2026). Przy `employment_type_pending`
   * to tylko domyślne B2B — ekrany mówią „do uzupełnienia”.
   */
  employment_type: EmploymentType | null;
  /** Forma do uzupełnienia (kartoteka założona z konta) — nie zdradza formy. */
  employment_type_pending: boolean;
  /** Przełożony do uzupełnienia (kartoteka z konta bez przełożonego). */
  manager_pending?: boolean;
  hired_on: string | null;
  work_start_date: string | null;
  last_working_day: string | null;
  timesheet_required: boolean;
  can_log_overtime: boolean;
  division?: Division | null;
  /** Uczeń/student na zleceniu bez składek ZUS do `contribution_exempt_until` (D8). */
  student_contribution_exempt?: boolean;
  /**
   * Pola zależne od formy — stąd do `suggested_entitlement_days`. Przełożony
   * i Kadry bez Płac dostają je bez kluczy (`HR_ONLY_FIELDS` w
   * `services/hr/people.py`): brak pola = nie dla czytającego, `null` = nieuzupełnione.
   */
  contribution_exempt_until?: string | null;
  /** Dzień po końcu zwolnienia — od niego Płace naliczają składki. */
  contributions_from?: string | null;
  /** Staż do urlopu na umowie o pracę (lata, z zaświadczeniem ZUS) — D9. */
  leave_seniority_years?: number | null;
  zus_certificate_received_on?: string | null;
  /** Podpowiedź wymiaru urlopu 20/26 z kartoteki (tylko UoP ze stażem). */
  suggested_entitlement_days?: number | null;
  roles: string[];
  entitlements?: LeaveEntitlementRow[];
  /**
   * Saldo płatnych dni do pierścienia w kartotece (`GET /api/hr/people/{id}`,
   * 19.10.2026): bez liczników rodzajów; `null` = bez puli albo moduł urlopów
   * zamknięty dla patrzącego; brak klucza = katalog.
   */
  leave_balance?: LeaveRing | null;
}

export type Person = PersonCard | PersonFull;

/** Własna kartoteka (`/api/hr/me`) — osoba zawsze widzi swoją formę. */
export type OwnProfile = PersonFull & { employment_type: EmploymentType };

export function isFullPerson(person: Person): person is PersonFull {
  return person.scope === "full";
}

export interface ProfileFields {
  manager_user_id?: number | null;
  employment_type?: EmploymentType;
  employment_status?: EmploymentStatus;
  hired_on?: string | null;
  work_start_date?: string | null;
  last_working_day?: string | null;
  default_location?: WorkLocation;
  timesheet_required?: boolean;
  can_log_overtime?: boolean;
  job_title?: string | null;
  department?: string | null;
  phone?: string | null;
  division?: Division | null;
  student_contribution_exempt?: boolean;
  contribution_exempt_until?: string | null;
  leave_seniority_years?: number | null;
  zus_certificate_received_on?: string | null;
}

export interface CompanyDayOff {
  id: number;
  day: string;
  name: string;
  kind: "company" | "bridge";
}

/** Nazwa formy — ze wspólnego słownika słów (`@/lib/hr-employment-terms`). */
export const EMPLOYMENT_TYPE_LABELS: Record<EmploymentType, string> = {
  uop: EMPLOYMENT_TERMS.uop.form,
  b2b: EMPLOYMENT_TERMS.b2b.form,
  zlecenie: EMPLOYMENT_TERMS.zlecenie.form,
};

export const EMPLOYMENT_STATUS_LABELS: Record<EmploymentStatus, string> = {
  pending: "Przed startem",
  onboarding: "Wejście",
  active: "Aktywny",
  offboarding: "Odejście w toku",
  exited: "Zakończył współpracę",
};

export const LOCATION_LABELS: Record<WorkLocation, string> = {
  onsite: "Biuro",
  remote: "Zdalnie",
};

export const HR_MODULE_LABELS: Record<HrModuleKey, string> = {
  people: "Ludzie (katalog i kartoteka)",
  leave: "Urlopy i zastępstwa",
  time: "Mój miesiąc (obecność i godziny)",
  payroll: "Płace i premie",
  lifecycle: "Wejście i odejście",
  care: "Opieka nad konsultantami",
  cases: "Sprawy administracja@",
  equipment: "Sprzęt i protokoły",
  settlements: "Rozliczenia zespołu",
  approvals: "Zgody na wydatki i premie poza umową",
};

/** Klucze zapytań „Ludzi” — wszystkie moduły HR mają wspólny korzeń `["hr"]`. */
export const hrKeys = {
  all: ["hr"] as const,
  config: ["hr", "config"] as const,
  people: ["hr", "people"] as const,
  person: (userId: number) => ["hr", "people", userId] as const,
  me: ["hr", "me"] as const,
  withoutProfile: ["hr", "admin", "users-without-profile"] as const,
  accountMismatches: ["hr", "people", "account-mismatches"] as const,
  daysOff: (year: number | null) => ["hr", "admin", "days-off", year] as const,
  availabilitySource: ["hr", "admin", "availability-source"] as const,
  counts: ["hr", "counts"] as const,
};

/** Pobiera plik modułu (PDF, XLSX, ZIP) z tokenem i zapisuje pod nazwą z serwera. */
export async function downloadHrFile(path: string, fallbackName: string): Promise<void> {
  const { blob, filename } = await fetchAuthenticatedDownload(path);
  downloadBlob(blob, filename ?? fallbackName);
}

export function useHrConfig(enabled = true) {
  return useQuery({
    queryKey: hrKeys.config,
    queryFn: async () => (await api.get<HrConfig>("/api/hr/config")).data,
    staleTime: 5 * 60 * 1000,
    enabled,
  });
}

/** Czy program „Ludzie w NEXUSIE” jest włączony (brak odpowiedzi = nie). */
export function useHrProgram(enabled = true): boolean {
  return useHrConfig(enabled).data?.program === true;
}

export function usePeople() {
  return useQuery({
    queryKey: hrKeys.people,
    queryFn: async () =>
      (await api.get<{ items: Person[]; total: number }>("/api/hr/people"))
        .data,
  });
}

export function usePerson(userId: number) {
  return useQuery({
    queryKey: hrKeys.person(userId),
    queryFn: async () =>
      (await api.get<Person>(`/api/hr/people/${userId}`)).data,
    enabled: Number.isFinite(userId) && userId > 0,
  });
}

export function useMyHrProfile() {
  return useQuery({
    queryKey: hrKeys.me,
    queryFn: async () =>
      (
        await api.get<
          ({ has_profile: true } & OwnProfile) | { has_profile: false }
        >("/api/hr/me")
      ).data,
  });
}

export function useUsersWithoutProfile(enabled: boolean) {
  return useQuery({
    queryKey: hrKeys.withoutProfile,
    queryFn: async () =>
      (
        await api.get<{
          items: { user_id: number; name: string; email: string }[];
        }>("/api/hr/admin/users-without-profile")
      ).data.items,
    enabled,
  });
}

/** Rozjazd kartoteka ↔ konto NEXUSA (decyzja Artura 19.10.2026: konto decyduje). */
export interface AccountMismatch {
  user_id: number;
  name: string;
  email: string;
  account_active: boolean;
  /** `null` = aktywne konto bez kartoteki. */
  employment_status: EmploymentStatus | null;
  proposed_status: EmploymentStatus;
  last_working_day: string | null;
  proposed_last_working_day: string | null;
  kind: "exit" | "return" | "missing";
  /** Podwładni do przepięcia w Strukturze (przy „exit”). */
  reports: number;
}

export interface AccountMismatches {
  items: AccountMismatch[];
  total: number;
  /** „Do uzupełnienia” w kartotekach: forma i przełożony. */
  pending: { employment_type: number; manager: number };
}

export function useAccountMismatches(enabled: boolean) {
  return useQuery({
    queryKey: hrKeys.accountMismatches,
    queryFn: async () =>
      (await api.get<AccountMismatches>("/api/hr/people/account-mismatches")).data,
    enabled,
  });
}

export function useAlignWithAccounts() {
  const invalidate = useInvalidatePeople();
  return useMutation({
    mutationFn: async (userIds: number[] | null) =>
      (
        await api.post<{ aligned: { exit: number; return: number; missing: number } }>(
          "/api/hr/people/account-mismatches/align",
          { user_ids: userIds },
        )
      ).data.aligned,
    onSuccess: invalidate,
  });
}

export type EmploymentTypeInput = Pick<
  ProfileFields,
  | "student_contribution_exempt"
  | "contribution_exempt_until"
  | "leave_seniority_years"
  | "zus_certificate_received_on"
> & { employment_type: EmploymentType };

/** Forma umowy osobną trasą — admin, Finanse i Kadry (19.10.2026). */
export function useSetEmploymentType(userId: number) {
  const invalidate = useInvalidatePeople();
  return useMutation({
    mutationFn: async (payload: EmploymentTypeInput) =>
      (
        await api.patch<PersonFull>(
          `/api/hr/people/${userId}/employment-type`,
          payload,
        )
      ).data,
    onSuccess: invalidate,
  });
}

function useInvalidatePeople() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: hrKeys.all });
}

export function useCreateProfile() {
  const invalidate = useInvalidatePeople();
  return useMutation({
    mutationFn: async (payload: ProfileFields & { user_id: number }) =>
      (await api.post<PersonFull>("/api/hr/admin/profiles", payload)).data,
    onSuccess: invalidate,
  });
}

export function useUpdateProfile(userId: number) {
  const invalidate = useInvalidatePeople();
  return useMutation({
    mutationFn: async (payload: ProfileFields) =>
      (await api.patch<PersonFull>(`/api/hr/admin/profiles/${userId}`, payload))
        .data,
    onSuccess: invalidate,
  });
}

export interface EntitlementInput {
  entitlement_days: string | null;
  carried_over_days: string;
  used_initial_days: string;
  reason?: string | null;
}

export function useSetEntitlement(userId: number) {
  const invalidate = useInvalidatePeople();
  return useMutation({
    mutationFn: async ({
      year,
      ...payload
    }: EntitlementInput & { year: number }) =>
      (
        await api.put<LeaveEntitlementRow>(
          `/api/hr/admin/profiles/${userId}/entitlements/${year}`,
          payload,
        )
      ).data,
    onSuccess: invalidate,
  });
}

export function useCompanyDaysOff(year: number | null, enabled = true) {
  return useQuery({
    queryKey: hrKeys.daysOff(year),
    queryFn: async () =>
      (
        await api.get<{ items: CompanyDayOff[] }>("/api/hr/admin/days-off", {
          params: year ? { year } : undefined,
        })
      ).data.items,
    enabled,
  });
}

export function useAddDayOff() {
  const invalidate = useInvalidatePeople();
  return useMutation({
    mutationFn: async (payload: Omit<CompanyDayOff, "id">) =>
      (await api.post<CompanyDayOff>("/api/hr/admin/days-off", payload)).data,
    onSuccess: invalidate,
  });
}

export function useRemoveDayOff() {
  const invalidate = useInvalidatePeople();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/api/hr/admin/days-off/${id}`);
    },
    onSuccess: invalidate,
  });
}

export function useSetHrModules() {
  const invalidate = useInvalidatePeople();
  return useMutation({
    mutationFn: async (modules: Partial<Record<HrModuleKey, boolean>>) =>
      (
        await api.put<{ modules: Record<HrModuleKey, boolean> }>(
          "/api/hr/admin/modules",
          { modules },
        )
      ).data,
    onSuccess: invalidate,
  });
}

export type AvailabilitySource = "compass" | "local";

/** Skąd zastępstwa i dni robocze biorą urlopy (admin; krok runbooka). */
export function useAvailabilitySource(enabled: boolean) {
  return useQuery({
    queryKey: hrKeys.availabilitySource,
    queryFn: async () =>
      (await api.get<{ source: AvailabilitySource }>("/api/hr/admin/availability-source"))
        .data.source,
    enabled,
  });
}

export function useSetAvailabilitySource() {
  const invalidate = useInvalidatePeople();
  return useMutation({
    mutationFn: async (source: AvailabilitySource) =>
      (
        await api.put<{ source: AvailabilitySource }>("/api/hr/admin/availability-source", {
          source,
        })
      ).data.source,
    onSuccess: invalidate,
  });
}

/** Stan pozycji menu modułu (czysta funkcja — test bez zapytań). */
export interface HrNavState {
  myTime: boolean;
  people: boolean;
  equipment: boolean;
  care: boolean;
}

/**
 * Stan menu modułu dla zalogowanej osoby. Praktykant ma własną powłokę i nie
 * pyta serwera; awaria odczytu = pozycje ukryte (serwer i tak broni tras).
 */
export function useHrNavState(
  user: { role: string; roles?: readonly string[] } | null | undefined,
): HrNavState {
  const roles = user
    ? new Set([user.role, ...(user.roles ?? [])])
    : new Set<string>();
  // Rada nadzorcza (0490) nie ma w menu ekranów „Ludzi” — bez zapytania.
  const ownShell = roles.size === 1 && (roles.has("trainee") || roles.has("board"));
  const { data } = useHrConfig(Boolean(user) && !ownShell);
  return hrNavState(data, CARE_ROLES.some((role) => roles.has(role)));
}

/** Role z kartami opieki (pozycja „Opieka nad konsultantami” i obszar „Opieka” na tablicy). */
export const CARE_ROLES = [
  "admin",
  "delivery_lead",
  "talent_community_manager",
  "head_of_recruitment",
] as const;

/**
 * Sprawy administracja@ są od 22.10.2026 w „Opiece” → „Do zrobienia” (wcześniej
 * zakładka „Sprawy” w „Ludziach”). Wchodzi tam też osoba bez roli opieki, gdy
 * ma uprawnienie „Sprawy” albo przypisaną sprawę — widzi wtedy same sprawy.
 */
export function casesInCare(
  config: Pick<HrConfig, "program" | "open_modules" | "me"> | null | undefined,
): boolean {
  if (!config?.program || !config.open_modules.care || !config.open_modules.cases) return false;
  const { me } = config;
  return me.cases || me.is_admin || me.has_assigned_cases === true;
}

export function hrNavState(config: HrConfig | undefined, careRole = false): HrNavState {
  if (!config?.program) return { myTime: false, people: false, equipment: false, care: false };
  const { me, open_modules: open } = config;
  const anyHrRight =
    me.people_admin || me.payroll || me.equipment || me.cases || me.timesheets === true;
  return {
    myTime: me.has_profile && (open.leave || open.time || open.people),
    people: open.people && (me.has_profile || anyHrRight || me.is_admin),
    equipment: open.equipment && (me.equipment || me.is_admin),
    // Role opieki albo same sprawy administracja@ (`casesInCare`).
    care: open.care && (careRole || casesInCare(config)),
  };
}

// ── Liczniki zakładek „Ludzi” (17.10.2026) ──────────────────────────────────
// `GET /api/hr/counts` (`backend/app/api/hr_counts.py`): `approvals` — wnioski
// i timesheety, o których osoba może zdecydować; `cases` — jej otwarte sprawy
// administracja@. `null` = liczba osoby nie dotyczy. Awaria albo odpowiedź
// w innym kształcie to błąd zapytania — zakładka nie pokazuje wtedy liczby.

export interface HrCounts {
  approvals: number | null;
  /** Zgody na wydatki i premie czekające na decyzję (0483); `null` — moduł nie działa. */
  consents: number | null;
  cases: number | null;
}

/**
 * Klucz mutacji, po których liczniki „Ludzi” liczą się od nowa (decyzja
 * o wniosku, anulowanie, decyzja o timesheecie). Mutacje z tym prefiksem
 * oznaczają moduły; licznik nie słucha już KAŻDEJ mutacji w aplikacji
 * (audyt wydajności 17.10.2026).
 */
export const HR_COUNTS_MUTATION_KEY = ["hr", "counts-change"] as const;

function countOrNull(value: unknown): number | null | undefined {
  if (value === null) return null;
  return typeof value === "number" && Number.isInteger(value) && value >= 0
    ? value
    : undefined;
}

export function parseHrCounts(raw: unknown): HrCounts {
  const body = (raw ?? {}) as Record<string, unknown>;
  const approvals = countOrNull(body.approvals);
  const cases = countOrNull(body.cases);
  // Backend sprzed zgód (0483) nie zna klucza — wtedy „nie dotyczy”.
  const consents = "consents" in body ? countOrNull(body.consents) : null;
  if (approvals === undefined || cases === undefined || consents === undefined) {
    throw new Error("Nieoczekiwana odpowiedź liczników „Ludzi”.");
  }
  return { approvals, consents, cases };
}

export function useHrCounts(enabled = true) {
  const queryClient = useQueryClient();
  const mutating = useIsMutating({ mutationKey: HR_COUNTS_MUTATION_KEY });
  const wasMutating = useRef(false);
  // Decyzja o wniosku, timesheecie albo sprawie zmienia liczby, a te mutacje
  // odświeżają tylko swój obszar — po zapisie oznaczonym `HR_COUNTS_MUTATION_KEY`
  // liczymy od nowa.
  useEffect(() => {
    if (mutating > 0) {
      wasMutating.current = true;
      return;
    }
    if (!wasMutating.current) return;
    wasMutating.current = false;
    void queryClient.invalidateQueries({ queryKey: hrKeys.counts });
  }, [mutating, queryClient]);
  return useQuery({
    queryKey: hrKeys.counts,
    queryFn: async () => parseHrCounts((await api.get<unknown>("/api/hr/counts")).data),
    enabled,
    staleTime: 30 * 1000,
  });
}
