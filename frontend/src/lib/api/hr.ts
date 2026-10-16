// „Ludzie w NEXUSIE” (16.10.2026) — katalog ludzi, kartoteka, Kadry.
//
// Lustro `backend/app/api/hr_people.py` i `backend/app/api/hr_admin.py`.
// Zakres widoczności liczy serwer (`scope`: wizytówka albo pełna kartoteka);
// front pokazuje to, co dostał. Stawek i kwot tu nie ma (moduł Płace).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type HrModuleKey =
  | "people"
  | "leave"
  | "time"
  | "payroll"
  | "lifecycle"
  | "care"
  | "cases"
  | "equipment";

export type EmploymentType = "uop" | "b2b" | "zlecenie";
export type EmploymentStatus =
  "pending" | "onboarding" | "active" | "offboarding" | "exited";
export type WorkLocation = "onsite" | "remote";

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
}

export interface PersonFull extends PersonCard {
  employment_type: EmploymentType;
  hired_on: string | null;
  work_start_date: string | null;
  last_working_day: string | null;
  timesheet_required: boolean;
  can_log_overtime: boolean;
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
}

export interface CompanyDayOff {
  id: number;
  day: string;
  name: string;
  kind: "company" | "bridge";
}

export const EMPLOYMENT_TYPE_LABELS: Record<EmploymentType, string> = {
  uop: "Umowa o pracę",
  b2b: "B2B",
  zlecenie: "Umowa zlecenie",
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
};

const keys = {
  config: ["hr", "config"] as const,
  people: ["hr", "people"] as const,
  person: (userId: number) => ["hr", "people", userId] as const,
  me: ["hr", "me"] as const,
  withoutProfile: ["hr", "admin", "users-without-profile"] as const,
  daysOff: (year: number | null) => ["hr", "admin", "days-off", year] as const,
};

export function useHrConfig(enabled = true) {
  return useQuery({
    queryKey: keys.config,
    queryFn: async () => (await api.get<HrConfig>("/api/hr/config")).data,
    staleTime: 5 * 60 * 1000,
    enabled,
  });
}

export function usePeople() {
  return useQuery({
    queryKey: keys.people,
    queryFn: async () =>
      (await api.get<{ items: Person[]; total: number }>("/api/hr/people"))
        .data,
  });
}

export function usePerson(userId: number) {
  return useQuery({
    queryKey: keys.person(userId),
    queryFn: async () =>
      (await api.get<Person>(`/api/hr/people/${userId}`)).data,
    enabled: Number.isFinite(userId) && userId > 0,
  });
}

export function useMyHrProfile() {
  return useQuery({
    queryKey: keys.me,
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
    queryKey: keys.withoutProfile,
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
  return () => queryClient.invalidateQueries({ queryKey: ["hr"] });
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
    queryKey: keys.daysOff(year),
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

/** Stan pozycji menu modułu (czysta funkcja — test bez zapytań). */
export interface HrNavState {
  myTime: boolean;
  people: boolean;
  equipment: boolean;
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
  if (!config) return { myTime: false, people: false, equipment: false };
  const { me, open_modules: open } = config;
  const anyHrRight = me.people_admin || me.payroll || me.equipment || me.cases;
  return {
    myTime: me.has_profile && (open.leave || open.time || open.people),
    people: open.people && (me.has_profile || anyHrRight || me.is_admin),
    equipment: open.equipment && (me.equipment || me.is_admin),
  };
}
