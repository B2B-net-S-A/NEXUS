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
  | "settlements";

export type EmploymentType = "uop" | "b2b" | "zlecenie";
export type EmploymentStatus =
  "pending" | "onboarding" | "active" | "offboarding" | "exited";
export type WorkLocation = "onsite" | "remote";
/** Pion firmy (17.10.2026): Front office — do podpisania zamówienia, Back office — po. */
export type Division = "front_office" | "back_office";

export interface HrConfig {
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
    /** Przypisany do sprawy administracja@ (bez uprawnienia widzi tylko swoje). */
    has_assigned_cases?: boolean;
    /** Head back office — edytuje ścieżkę wejścia „Konsultant u klienta” (O4). */
    back_office_head?: boolean;
    /** Kogo osoba zastępuje dziś (przełożony na urlopie z nią jako zastępcą). */
    covering?: { manager_user_id: number; manager_name: string; until: string; reports: number }[];
  };
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
}

export interface LeaveEntitlementRow {
  year: number;
  entitlement_days: string | null;
  carried_over_days: string;
  used_initial_days: string;
  /** Odpowiedź zapisu: podpowiedź wymiaru 20/26 z kartoteki (D9). */
  suggested_entitlement_days?: number | null;
}

export interface PersonFull extends PersonCard {
  employment_type: EmploymentType;
  hired_on: string | null;
  work_start_date: string | null;
  last_working_day: string | null;
  timesheet_required: boolean;
  can_log_overtime: boolean;
  division?: Division | null;
  /** Uczeń/student na zleceniu bez składek ZUS do `contribution_exempt_until` (D8). */
  student_contribution_exempt?: boolean;
  /**
   * Pola Kadr — stąd do `suggested_entitlement_days`. Przełożony dostaje je
   * bez kluczy (`HR_ONLY_FIELDS` w `services/hr/people.py`): brak pola = nie
   * dla niego, `null` = Kadry nie uzupełniły.
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
}

export type Person = PersonCard | PersonFull;

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
};

/** Klucze zapytań „Ludzi” — wszystkie moduły HR mają wspólny korzeń `["hr"]`. */
export const hrKeys = {
  all: ["hr"] as const,
  config: ["hr", "config"] as const,
  people: ["hr", "people"] as const,
  person: (userId: number) => ["hr", "people", userId] as const,
  me: ["hr", "me"] as const,
  withoutProfile: ["hr", "admin", "users-without-profile"] as const,
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
          ({ has_profile: true } & PersonFull) | { has_profile: false }
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
  const traineeOnly = roles.size === 1 && roles.has("trainee");
  const { data } = useHrConfig(Boolean(user) && !traineeOnly);
  return hrNavState(data);
}

export function hrNavState(config: HrConfig | undefined): HrNavState {
  if (!config) return { myTime: false, people: false, equipment: false, care: false };
  const { me, open_modules: open } = config;
  const anyHrRight = me.people_admin || me.payroll || me.equipment || me.cases;
  return {
    myTime: me.has_profile && (open.leave || open.time || open.people),
    people: open.people && (me.has_profile || anyHrRight || me.is_admin),
    equipment: open.equipment && (me.equipment || me.is_admin),
    // Kto z ról widzi pozycję, rozstrzyga `roles` w `nav-registry`.
    care: open.care,
  };
}

// ── Liczniki zakładek „Ludzi” (17.10.2026) ──────────────────────────────────
// `GET /api/hr/counts` (`backend/app/api/hr_counts.py`): `approvals` — wnioski
// i timesheety, o których osoba może zdecydować; `cases` — jej otwarte sprawy
// administracja@. `null` = liczba osoby nie dotyczy. Awaria albo odpowiedź
// w innym kształcie to błąd zapytania — zakładka nie pokazuje wtedy liczby.

export interface HrCounts {
  approvals: number | null;
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
  if (approvals === undefined || cases === undefined) {
    throw new Error("Nieoczekiwana odpowiedź liczników „Ludzi”.");
  }
  return { approvals, cases };
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
