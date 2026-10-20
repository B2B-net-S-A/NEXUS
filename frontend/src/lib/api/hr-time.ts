// „Mój miesiąc” (16.10.2026) — obecność i godziny w jednym ekranie,
// timesheety, akceptacje, PDF z sumą kontrolną.
//
// Lustro `backend/app/api/hr_time.py`. Reguły (8 h na dzień, nadgodziny,
// urlop blokuje dzień, zakres akceptującego) liczy serwer; front pokazuje
// stan i podaje komunikat z `detail`. Stawek ani kwot tu nie ma.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { payrollKeys } from "@/lib/api/hr-payroll";
import { teamKeys } from "@/lib/api/hr-team";

import { HR_COUNTS_MUTATION_KEY, type WorkLocation } from "./hr";

export type TimesheetStatus = "draft" | "submitted" | "approved";
export type EntrySource = "manual" | "leave_paid" | "template" | "compass_import";

export interface TimesheetEntry {
  id: number;
  work_date: string;
  hours: number;
  project: string | null;
  description: string;
  source: EntrySource;
  is_overtime: boolean;
  overtime_reason: string | null;
}

export interface TimesheetHeader {
  id: number;
  status: TimesheetStatus;
  submitted_at: string | null;
  return_note: string | null;
  returned_at: string | null;
  approved_at: string | null;
  approved_by_name: string | null;
  payroll_locked: boolean;
  pdf_hash: string | null;
}

export interface DayLeave {
  status: "pending" | "approved";
  fraction: number;
  full: boolean;
  /** Płatny urlop B2B/zlecenia z puli — dzień rozlicza się jak praca (auto-wpis). */
  paid_work: boolean;
  paid_hours: number;
  /** Rodzaj (osoba, przełożony, Kadry) albo „Nieobecność”. */
  label: string;
}

export interface MonthDay {
  date: string;
  /** 1 = poniedziałek … 7 = niedziela. */
  weekday: number;
  is_weekend: boolean;
  holiday: string | null;
  day_off: string | null;
  working_day: boolean;
  location: WorkLocation | null;
  location_source: "default" | "exception" | null;
  attendance_status: "active" | "business_trip" | null;
  attendance_note: string | null;
  leave: DayLeave | null;
  entries: TimesheetEntry[];
  hours: number;
  /** Godziny do wpisania bez nadgodzin; `null` = dzień zablokowany urlopem. */
  capacity: number | null;
  overtime_hours: number;
}

export interface MonthTotals {
  work_hours: number;
  leave_paid_hours: number;
  overtime_hours: number;
  leave_days: number;
  working_days: number;
  norm_hours: number;
  days_missing: number;
}

export interface MonthView {
  user_id: number;
  name: string;
  year: number;
  month: number;
  deadline: string;
  employment_type: "uop" | "b2b" | "zlecenie";
  default_location: WorkLocation;
  can_log_overtime: boolean;
  /** Przełożony z kartoteki (bez niego akceptują Kadry). */
  approver_name: string | null;
  timesheet: TimesheetHeader | null;
  days: MonthDay[];
  totals: MonthTotals;
}

export interface EntryInput {
  work_date: string;
  hours: number;
  project?: string | null;
  description: string;
  overtime_reason?: string | null;
}

export type EntryPatch = Partial<EntryInput>;

export interface DayHint {
  day: string;
  counts: {
    calls: number;
    stage_moves: number;
    verifications: number;
    cv_sent: number;
    client_interviews: number;
    notes: number;
  };
  jobs: string[];
  client_interviews: { time: string; job: string | null }[];
  text: string | null;
}

export interface TimesheetTemplate {
  id: number;
  name: string;
  description: string;
  project: string | null;
  sort_order: number;
}

export interface TemplateInput {
  name: string;
  description: string;
  project?: string | null;
  sort_order?: number;
}

/** Okno „Wypełnij miesiąc” (jak Compass): godziny dziennie, źródło opisu, nadpisanie. */
export interface FillInput {
  project?: string | null;
  description?: string | null;
  template_id?: number | null;
  /** Brak = 8 h; serwer przyjmuje (0, 8] — nadgodziny wpisuje się w dniu. */
  hours_per_day?: number;
  /** Kasuje wpisy szkicu (poza auto-wpisami płatnej puli) przed wypełnieniem. */
  overwrite?: boolean;
}

export interface FillResult {
  inserted: number;
  skipped_existing: number;
  skipped_leave: number;
  working_days: number;
  /** Wpisy skasowane przez „nadpisz istniejące wpisy”. */
  removed: number;
  hours_per_day: number;
  description: string;
  project: string | null;
}

/** Domyślny opis Kadr (Ustawienia → Kadry): rola → etykieta, projekt, opis. */
export interface RoleDefault {
  id: number;
  label: string;
  /** Rola NEXUSA; `null` = dla wszystkich ról. */
  applies_to_role: string | null;
  project: string | null;
  default_description: string;
  is_active: boolean;
  sort_order: number;
}

export type RoleDefaultInput = Partial<Omit<RoleDefault, "id">>;

export type QueueStatus = TimesheetStatus | "missing";

export interface TeamQueueItem {
  user_id: number;
  name: string;
  job_title: string | null;
  timesheet: TimesheetHeader | null;
  status: QueueStatus;
  hours: number;
  overtime_hours: number;
  absence_days: number;
  can_decide: boolean;
}

/** Kolejka „Akceptacji” za miesiąc (`GET /api/hr/time/team/{rok}/{miesiąc}`). */
export interface TeamQueue {
  year: number;
  month: number;
  /** Norma miesiąca: dni robocze kalendarza firmy × 8 h (jak w „Moim miesiącu”). */
  norm_hours: number;
  items: TeamQueueItem[];
}

export const TIMESHEET_STATUS_LABELS: Record<QueueStatus, string> = {
  draft: "Szkic",
  submitted: "Do akceptacji",
  approved: "Zaakceptowany",
  missing: "Nie założony",
};

/** Wiersz archiwum „Mój miesiąc” (`GET /me/history`, ostatnie 12 timesheetów). */
export interface TimesheetHistoryItem {
  id: number;
  year: number;
  month: number;
  status: TimesheetStatus;
  approved_at: string | null;
  hours: number;
}

export const timeKeys = {
  all: ["hr", "time"] as const,
  month: (year: number, month: number) => ["hr", "time", "me", year, month] as const,
  history: ["hr", "time", "me", "history"] as const,
  templates: ["hr", "time", "templates"] as const,
  roleDefaults: ["hr", "time", "role-defaults"] as const,
  hint: (day: string) => ["hr", "time", "hint", day] as const,
  team: (year: number, month: number) => ["hr", "time", "team", year, month] as const,
  member: (userId: number, year: number, month: number) =>
    ["hr", "time", "team", userId, year, month] as const,
};

/** Ścieżki API (jedno miejsce — także dla pobrań plików). */
export const timePaths = {
  month: (year: number, month: number) => `/api/hr/time/me/${year}/${month}`,
  myPdf: (year: number, month: number) => `/api/hr/time/me/${year}/${month}/pdf`,
  timesheetPdf: (id: number) => `/api/hr/time/timesheets/${id}/pdf`,
  monthZip: (year: number, month: number) => `/api/hr/time/export/${year}/${month}/zip`,
  /** CSV godzin: miesiące `RRRR-MM` od–do (najwyżej 24). */
  myCsv: (from: string, to: string) =>
    `/api/hr/time/me/export.csv?${new URLSearchParams({ from, to })}`,
  personCsv: (userId: number, from: string, to: string) =>
    `/api/hr/time/people/${userId}/export.csv?${new URLSearchParams({ from, to })}`,
  monthCsv: (year: number, month: number) => `/api/hr/time/export/${year}/${month}/csv`,
};

export function useMyMonth(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: timeKeys.month(year, month),
    queryFn: async () => (await api.get<MonthView>(timePaths.month(year, month))).data,
    enabled,
  });
}

export function useMyTimesheetHistory(enabled = true) {
  return useQuery({
    queryKey: timeKeys.history,
    queryFn: async () =>
      (await api.get<{ items: TimesheetHistoryItem[] }>("/api/hr/time/me/history")).data.items,
    enabled,
  });
}

export function useMyTemplates(enabled = true) {
  return useQuery({
    queryKey: timeKeys.templates,
    queryFn: async () =>
      (
        await api.get<{
          items: TimesheetTemplate[];
          role_default: { label: string; description: string; project: string | null } | null;
        }>("/api/hr/time/me/templates")
      ).data,
    enabled,
    staleTime: 60_000,
  });
}

export function useDayHint(day: string | null) {
  return useQuery({
    queryKey: timeKeys.hint(day ?? ""),
    queryFn: async () =>
      (await api.get<DayHint>("/api/hr/time/me/suggestion", { params: { day } })).data,
    enabled: Boolean(day),
    staleTime: 60_000,
  });
}

// Godziny i statusy timesheetów widać też w Płacach i w „Moim zespole”.
const TIME_AFFECTS = [timeKeys.all, payrollKeys.all, teamKeys.all] as const;

function useInvalidateTime() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all(
      TIME_AFFECTS.map((queryKey) => queryClient.invalidateQueries({ queryKey })),
    );
}

export function useSaveMyEntry(year: number, month: number) {
  const invalidate = useInvalidateTime();
  return useMutation({
    mutationFn: async ({ id, ...payload }: EntryPatch & { id?: number }) =>
      id
        ? (await api.patch<TimesheetEntry>(`/api/hr/time/me/entries/${id}`, payload)).data
        : (
            await api.post<TimesheetEntry>(
              `/api/hr/time/me/${year}/${month}/entries`,
              payload,
            )
          ).data,
    onSuccess: invalidate,
  });
}

export function useDeleteMyEntry() {
  const invalidate = useInvalidateTime();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/api/hr/time/me/entries/${id}`);
    },
    onSuccess: invalidate,
  });
}

export function useSetAttendance() {
  const invalidate = useInvalidateTime();
  return useMutation({
    mutationFn: async ({
      day,
      ...payload
    }: {
      day: string;
      status: "active" | "business_trip";
      location: WorkLocation | null;
      note?: string | null;
    }) => (await api.put(`/api/hr/time/me/attendance/${day}`, payload)).data,
    onSuccess: invalidate,
  });
}

export function useFillMonth(year: number, month: number) {
  const invalidate = useInvalidateTime();
  return useMutation({
    mutationFn: async (payload: FillInput) =>
      (await api.post<FillResult>(`/api/hr/time/me/${year}/${month}/fill`, payload)).data,
    onSuccess: invalidate,
  });
}

// ── Moje szablony opisów ─────────────────────────────────────────────────────

function useInvalidateTemplates() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: timeKeys.templates });
}

export function useSaveTemplate() {
  const invalidate = useInvalidateTemplates();
  return useMutation({
    mutationFn: async ({ id, ...payload }: Partial<TemplateInput> & { id?: number }) =>
      id
        ? (await api.patch<TimesheetTemplate>(`/api/hr/time/me/templates/${id}`, payload)).data
        : (await api.post<TimesheetTemplate>("/api/hr/time/me/templates", payload)).data,
    onSuccess: invalidate,
  });
}

export function useDeleteTemplate() {
  const invalidate = useInvalidateTemplates();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/api/hr/time/me/templates/${id}`);
    },
    onSuccess: invalidate,
  });
}

/**
 * Kolejność wierszy (szablony, domyślne opisy): `sort_order` = pozycja na
 * liście, zapis tylko tych, które się przesunęły.
 */
export function reorderedSortOrders<T extends { id: number; sort_order: number }>(
  items: readonly T[],
): { id: number; sort_order: number }[] {
  return items
    .map((item, index) => ({ id: item.id, sort_order: index, before: item.sort_order }))
    .filter((item) => item.sort_order !== item.before)
    .map(({ id, sort_order }) => ({ id, sort_order }));
}

export function useReorderTemplates() {
  const invalidate = useInvalidateTemplates();
  return useMutation({
    mutationFn: async (ordered: readonly TimesheetTemplate[]) => {
      for (const change of reorderedSortOrders(ordered)) {
        await api.patch(`/api/hr/time/me/templates/${change.id}`, {
          sort_order: change.sort_order,
        });
      }
    },
    onSettled: invalidate,
  });
}

// ── Domyślne opisy (Kadry) ───────────────────────────────────────────────────

export function useRoleDefaults(enabled = true) {
  return useQuery({
    queryKey: timeKeys.roleDefaults,
    queryFn: async () =>
      (await api.get<{ items: RoleDefault[] }>("/api/hr/time/role-defaults")).data.items,
    enabled,
  });
}

// Domyślny opis roli widać też w „Moim miesiącu” (okno „Wypełnij miesiąc”).
function useInvalidateRoleDefaults() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all(
      [timeKeys.roleDefaults, timeKeys.templates].map((queryKey) =>
        queryClient.invalidateQueries({ queryKey }),
      ),
    );
}

export function useSaveRoleDefault() {
  const invalidate = useInvalidateRoleDefaults();
  return useMutation({
    mutationFn: async ({ id, ...payload }: RoleDefaultInput & { id?: number }) =>
      id
        ? (await api.patch<RoleDefault>(`/api/hr/time/role-defaults/${id}`, payload)).data
        : (await api.post<RoleDefault>("/api/hr/time/role-defaults", payload)).data,
    onSuccess: invalidate,
  });
}

export function useDeleteRoleDefault() {
  const invalidate = useInvalidateRoleDefaults();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/api/hr/time/role-defaults/${id}`);
    },
    onSuccess: invalidate,
  });
}

export function useReorderRoleDefaults() {
  const invalidate = useInvalidateRoleDefaults();
  return useMutation({
    mutationFn: async (ordered: readonly RoleDefault[]) => {
      for (const change of reorderedSortOrders(ordered)) {
        await api.patch(`/api/hr/time/role-defaults/${change.id}`, {
          sort_order: change.sort_order,
        });
      }
    },
    onSettled: invalidate,
  });
}

export function useCopyPrevious(year: number, month: number) {
  const invalidate = useInvalidateTime();
  return useMutation({
    mutationFn: async () =>
      (
        await api.post<{
          source: { year: number; month: number } | null;
          inserted: number;
          skipped_no_source: number;
        }>(`/api/hr/time/me/${year}/${month}/copy-previous`)
      ).data,
    onSuccess: invalidate,
  });
}

export function useSubmitMonth(year: number, month: number) {
  const invalidate = useInvalidateTime();
  return useMutation({
    mutationFn: async () =>
      (await api.post<TimesheetHeader>(`/api/hr/time/me/${year}/${month}/submit`)).data,
    onSuccess: invalidate,
  });
}

export function useTeamQueue(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: timeKeys.team(year, month),
    queryFn: async () =>
      (
        await api.get<TeamQueue>(`/api/hr/time/team/${year}/${month}`)
      ).data,
    enabled,
  });
}

export function useTeamMemberMonth(
  userId: number | null,
  year: number,
  month: number,
) {
  return useQuery({
    queryKey: timeKeys.member(userId ?? 0, year, month),
    queryFn: async () =>
      (await api.get<MonthView>(`/api/hr/time/team/${userId}/${year}/${month}`)).data,
    enabled: userId != null && userId > 0,
  });
}

export function useSaveTeamEntry(userId: number, year: number, month: number) {
  const invalidate = useInvalidateTime();
  return useMutation({
    mutationFn: async ({ id, ...payload }: EntryPatch & { id?: number }) =>
      id
        ? (await api.patch<TimesheetEntry>(`/api/hr/time/team/entries/${id}`, payload)).data
        : (
            await api.post<TimesheetEntry>(
              `/api/hr/time/team/${userId}/${year}/${month}/entries`,
              payload,
            )
          ).data,
    onSuccess: invalidate,
  });
}

export function useDeleteTeamEntry() {
  const invalidate = useInvalidateTime();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/api/hr/time/team/entries/${id}`);
    },
    onSuccess: invalidate,
  });
}

export type TimesheetDecision = "approve" | "return" | "revoke";

export function useDecideTimesheet() {
  const invalidate = useInvalidateTime();
  return useMutation({
    // Licznik „Akceptacji” liczy się od nowa po decyzji o timesheecie.
    mutationKey: [...HR_COUNTS_MUTATION_KEY, "timesheet-decision"],
    mutationFn: async ({
      id,
      decision,
      note,
    }: {
      id: number;
      decision: TimesheetDecision;
      note?: string;
    }) =>
      (
        await api.post<TimesheetHeader>(
          `/api/hr/time/timesheets/${id}/${decision}`,
          decision === "return" ? { note } : undefined,
        )
      ).data,
    onSuccess: invalidate,
  });
}

/** Wynik „Przypomnij” (`POST /api/hr/time/remind/{osoba}/{rok}/{miesiąc}`). */
export interface TimesheetReminderResult {
  /** `person` — szkic albo brak raportu; `approver` — raport czeka na akceptację. */
  target: "person" | "approver";
  status: "missing" | "draft" | "submitted";
  sent: boolean;
  /** Ten sam adresat dostał już dziś przypomnienie — nic nie wyszło drugi raz. */
  already_today: boolean;
}

/**
 * „Przypomnij” o timesheecie osoby za miesiąc: osobie (szkic, brak) albo
 * akceptującym (wysłany). Płace, Kadry, admin i akceptujący tej osoby; raz
 * dziennie na adresata. Używają go Płace i „Akceptacje”.
 */
export function useRemindTimesheet() {
  return useMutation({
    mutationFn: async ({ userId, year, month }: { userId: number; year: number; month: number }) =>
      (
        await api.post<TimesheetReminderResult>(
          `/api/hr/time/remind/${userId}/${year}/${month}`,
        )
      ).data,
  });
}

/** Komunikat po „Przypomnij” (czysta funkcja — test bez renderu). */
export function reminderToast(result: TimesheetReminderResult, name: string): string {
  if (result.already_today) return `${name}: przypomnienie poszło już dziś.`;
  return result.target === "approver"
    ? `Przypomnienie poszło do akceptującego — ${name}.`
    : `Przypomnienie poszło do: ${name}.`;
}
