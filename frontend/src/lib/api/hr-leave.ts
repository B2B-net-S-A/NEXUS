// „Ludzie w NEXUSIE” (16.10.2026) — urlopy i zastępstwa.
//
// Lustro `backend/app/api/hr_leave.py`. Reguły (pula, limity, kto decyduje,
// kto widzi rodzaj nieobecności) liczy serwer; front pokazuje to, co dostał.
// D6: „Nieobecni dziś”, plakietka przy osobie i kalendarz zespołu nie niosą
// rodzaju nieobecności — dostaje go tylko osoba, jej przełożony i Kadry.
// D5 (etap 2): na B2B i zleceniu nieobecność jest zgłoszeniem — wchodzi od razu
// (`is_report`), koordynator widzi ją „do wiadomości” i może zgłosić kolizję.
// Załącznik (potwierdzenie nieobecności w e-teczce): osoba dołącza i usuwa
// własny plik, Kadry pobierają; przełożony dostaje tylko `proof_count`.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { downloadBlob, fetchAuthenticatedDownload } from "@/lib/authenticated-files";
import { HR_COUNTS_MUTATION_KEY, hrKeys, useHrConfig, type EmploymentType } from "@/lib/api/hr";
import { SUBSTITUTION_QUERY_KEY } from "@/lib/api/hr-dashboard";
import { payrollKeys } from "@/lib/api/hr-payroll";
import { teamKeys } from "@/lib/api/hr-team";
import { timeKeys } from "@/lib/api/hr-time";
import { WS_BACKED_SAFETY_POLL_MS } from "@/lib/polling";
import { useAuthStore } from "@/store/auth";

export type LeaveType =
  | "vacation"
  | "on_demand"
  | "occasional"
  | "childcare"
  | "care_leave"
  | "force_majeure"
  | "sick_leave"
  | "maternity"
  | "paternity"
  | "parental_leave"
  | "childrearing"
  | "unpaid_leave"
  | "blood_donation"
  | "training"
  | "holiday_in_lieu"
  | "other";

export type LeaveStatus = "pending" | "approved" | "rejected" | "cancelled";
export type HalfDay = "morning" | "afternoon";

export interface LeaveBalance {
  year: number;
  employment_type: EmploymentType;
  has_pool: boolean;
  /** Pula z dniami płatnymi (> 0) — UoP albo kontraktor z umowną pulą. */
  has_paid_pool: boolean;
  entitlement_days: string | null;
  carried_over_days: string | null;
  used_initial_days: string | null;
  /** „Dziś” serwera (kalendarz firmy), od którego liczy wykorzystane i zaplanowane. */
  as_of: string;
  approved_days: string;
  /**
   * Wykorzystane do dziś włącznie (przy puli: dni płatne + sprzed NEXUSA),
   * zaplanowane = zatwierdzone po dziś, `pending_days` = czeka. Bez płatnej
   * puli to wszystkie dni nieobecności (bez wynagrodzenia).
   */
  used_days: string;
  planned_days: string;
  pending_days: string;
  unpaid_days: string;
  remaining_days: string | null;
  on_demand_used: string | null;
  on_demand_limit: string | null;
  childcare_used: string | null;
  childcare_limit: string | null;
  allowed_types: LeaveType[];
}

export interface LeaveRequestRow {
  id: string;
  /** Miesiące płac już zamknięte, których dotyczy zmiana (godziny zostają w zamrożonych liniach). */
  payroll_locked_months?: string[];
  /** Zdanie dla osoby przy zmianie w zamkniętym miesiącu płac (Płace dostały dzwonek). */
  payroll_warning?: string | null;
  user_id: number;
  user_name: string | null;
  /** `null` w kolejce zastępcy przy L4 i pokrewnych (D6) — etykieta to wtedy „Nieobecność”. */
  leave_type: LeaveType | null;
  leave_type_label: string;
  status: LeaveStatus;
  start_date: string;
  end_date: string;
  half_day: HalfDay | null;
  days_total: string;
  paid_days: string;
  unpaid_days: string;
  note: string | null;
  substitute_user_id: number | null;
  substitute_name: string | null;
  forward_mail_consent: boolean;
  oof_internal_message: string | null;
  oof_external_message: string | null;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_note: string | null;
  source: "self" | "on_behalf" | "outlook_oof" | "compass_import";
  created_at: string | null;
  can_cancel: boolean;
  /** Zgłoszenie z B2B albo zlecenia (D5) — bez akceptacji i odrzucenia. */
  is_report?: boolean;
  employment_type?: EmploymentType | null;
  /** Ostatnia kolizja zgłoszona przez koordynatora. */
  conflict?: LeaveConflictInfo | null;
  /** Ile plików jest przy wniosku; `null` u zastępcy przy rodzaju ukrytym (D6). */
  proof_count?: number | null;
  /** Pliki z pobraniem — tylko osoba i Kadry; przełożony dostaje `null`. */
  proofs?: LeaveProof[] | null;
  /** Osoba może dołączyć plik (własny wniosek, oczekuje albo zatwierdzony). */
  can_add_proof?: boolean;
}

export interface LeaveProof {
  id: number;
  file_name: string;
  mime: string;
  size_bytes: number;
  created_at: string | null;
  /** Osoba usuwa tylko plik, który sama dodała. */
  can_remove: boolean;
}

export interface LeaveConflictInfo {
  at: string | null;
  by_name: string | null;
  note: string | null;
}

export interface WorkSummary {
  total: number;
  by_kind: { kind: string; label: string; count: number }[];
  /** `title` tylko we własnym podglądzie — za kogoś serwer go nie oddaje (nazwiska kandydatów). */
  items: { kind: string; label: string; starts_at: string; title: string | null }[];
}

export interface ColleagueAbsence {
  user_id: number;
  name: string;
  start_date: string;
  end_date: string;
}

export interface PendingLeaveRow extends LeaveRequestRow {
  department: string | null;
  manager_name: string | null;
  work_total: number;
  work_by_kind: WorkSummary["by_kind"];
  department_absent: ColleagueAbsence[];
  /**
   * Wniosek widoczny, bo patrzący zastępuje dziś przełożonego tej osoby
   * (imię przełożonego); `null` = własny zespół, Kadry albo admin.
   */
  as_substitute_for?: string | null;
  as_substitute_until?: string | null;
  /** `false` = zastępca widzi „Nieobecność” (L4 i pokrewne) i tylko przyjmuje do wiadomości. */
  type_visible?: boolean;
  can_decide?: boolean;
  /** Zgłoszenie do wiadomości — koordynator może zgłosić kolizję (D5). */
  can_report_conflict?: boolean;
}

/** Kogo patrzący zastępuje dziś (przełożony na urlopie z nim jako zastępcą). */
export interface LeaveCovering {
  manager_user_id: number;
  manager_name: string;
  until: string;
  reports: number;
}

interface PendingLeavePayload {
  items: PendingLeaveRow[];
  total: number;
  covering?: LeaveCovering[];
  /** Zgłoszenia z B2B i zlecenia „do wiadomości” (D5) — poza licznikiem decyzji. */
  reported?: PendingLeaveRow[];
}

export interface LeaveYearSplit {
  year: number;
  requested: string;
  paid: string;
  unpaid: string;
  has_pool: boolean;
  remaining_before: string | null;
  remaining_after: string | null;
}

export interface LeavePreview {
  working_days: string[];
  days_total: string;
  paid_days: string;
  unpaid_days: string;
  years: LeaveYearSplit[];
  blocking_reason: string | null;
  auto_approved: boolean;
  /** Forma osoby — słowa okna (D4). */
  employment_type?: EmploymentType;
  /** `report` — zgłoszenie bez akceptacji (B2B, zlecenie, D5); `request` — wniosek. */
  flow?: "request" | "report";
  /** Akceptujący (wniosek) albo koordynator, który dostanie informację (zgłoszenie). */
  approver: string;
  department_absent: ColleagueAbsence[];
  work: WorkSummary;
  substitute_absent: boolean;
  return_on: string | null;
}

export interface SubstituteCandidate {
  user_id: number;
  name: string;
  job_title: string | null;
  department: string | null;
  same_department: boolean;
  shared_role: boolean;
  suggested: boolean;
}

export interface LeaveInput {
  leave_type: LeaveType;
  start_date: string;
  end_date: string;
  half_day?: HalfDay | null;
  note?: string | null;
  substitute_user_id?: number | null;
  forward_mail_consent?: boolean;
  oof_internal_message?: string | null;
  oof_external_message?: string | null;
}

/** Wpis za pracownika — bez zgody na przekierowanie i tekstów OOF (należą do osoby). */
export type OnBehalfInput = Omit<
  LeaveInput,
  "forward_mail_consent" | "oof_internal_message" | "oof_external_message"
> & { user_id: number };

export interface OnBehalfPerson {
  user_id: number;
  name: string;
  employment_type: EmploymentType;
  department: string | null;
  /** D5: za osobę na B2B/zleceniu wpisują tylko Kadry i admin (lista służy też filtrowi historii). */
  can_enter?: boolean;
}

/** Osoby, którym patrzący może wpisać nieobecność (bez `can_enter: false`). */
export function enterablePeople(rows: OnBehalfPerson[] | undefined): OnBehalfPerson[] {
  return (rows ?? []).filter((row) => row.can_enter !== false);
}

export type CalendarDayKind = "work" | "weekend" | "holiday" | "company";

export interface CalendarAbsence {
  /** Tylko w kręgu D6 (osoba, przełożony, Kadry). */
  id: string | null;
  start_date: string;
  end_date: string;
  half_day: HalfDay | null;
  status: "approved" | "pending";
  label: string;
  /** Tylko w kręgu D6; poza nim zawsze `null`. */
  leave_type: LeaveType | null;
  substitute_user_id: number | null;
  substitute_name: string | null;
}

/** Wyjątek obecności z „Mojego miesiąca” (nie rodzaj nieobecności, bez notatki). */
export type CalendarPresenceKind = "remote" | "business_trip";

export interface CalendarPresence {
  date: string;
  kind: CalendarPresenceKind;
}

export interface TeamCalendarPerson {
  user_id: number;
  name: string;
  department: string | null;
  job_title: string | null;
  is_me: boolean;
  type_visible: boolean;
  absences: CalendarAbsence[];
  /** Praca zdalna i delegacja — pusta lista, gdy moduł czasu jest zamknięty. */
  presence?: CalendarPresence[];
}

export interface TeamCalendar {
  month: string;
  today: string;
  days: { date: string; weekday: number; kind: CalendarDayKind; name: string | null }[];
  departments: string[];
  /** Czy serwer dołączył pracę zdalną i delegację (moduł czasu otwarty). */
  presence_shown?: boolean;
  people: TeamCalendarPerson[];
}

export interface AbsentTodayRow {
  user_id: number;
  name: string | null;
  until: string;
  half_day: HalfDay | null;
  substitute_user_id: number | null;
  substitute_name: string | null;
  substitute_absent: boolean;
  i_substitute: boolean;
  is_me: boolean;
}

export interface PersonAbsence {
  user_id: number;
  until: string;
  half_day: HalfDay | null;
  substitute_user_id: number | null;
  substitute_name: string | null;
}

const ROOT = "/api/hr/leave";

export const leaveKeys = {
  all: ["hr", "leave"] as const,
  balance: (year: number) => ["hr", "leave", "balance", year] as const,
  mine: ["hr", "leave", "mine"] as const,
  preview: (scope: string, input: unknown) => ["hr", "leave", "preview", scope, input] as const,
  substitutes: (scope: string, start: string, end: string) =>
    ["hr", "leave", "substitutes", scope, start, end] as const,
  pending: ["hr", "leave", "approvals", "pending"] as const,
  history: (filters: unknown) => ["hr", "leave", "approvals", "history", filters] as const,
  people: ["hr", "leave", "approvals", "people"] as const,
  calendar: (month: string, department: string | null, team: boolean) =>
    ["hr", "leave", "calendar", month, department, team] as const,
  absentToday: ["hr", "leave", "absent-today"] as const,
  absence: (ids: string, on: string | null) => ["hr", "leave", "absence", ids, on] as const,
};

export function useLeaveBalance(year: number, enabled = true) {
  return useQuery({
    queryKey: leaveKeys.balance(year),
    queryFn: async () =>
      (await api.get<LeaveBalance>(`${ROOT}/balance`, { params: { year } })).data,
    enabled,
  });
}

export function useMyLeaveRequests(enabled = true) {
  return useQuery({
    queryKey: leaveKeys.mine,
    queryFn: async () =>
      (await api.get<{ items: LeaveRequestRow[] }>(`${ROOT}/my-requests`)).data.items,
    enabled,
  });
}

/** Podgląd podziału i ostrzeżeń — bez zapisu; `onBehalfOf` = ścieżka akceptującego. */
export function useLeavePreview(
  input: LeaveInput | null,
  onBehalfOf: number | null = null,
) {
  const scope = onBehalfOf ? `user-${onBehalfOf}` : "self";
  return useQuery({
    queryKey: leaveKeys.preview(scope, input),
    queryFn: async () => {
      if (!input) throw new Error("brak danych wniosku");
      const path = onBehalfOf ? `${ROOT}/approvals/preview` : `${ROOT}/preview`;
      const body = onBehalfOf
        ? {
            leave_type: input.leave_type,
            start_date: input.start_date,
            end_date: input.end_date,
            half_day: input.half_day ?? null,
            substitute_user_id: input.substitute_user_id ?? null,
            user_id: onBehalfOf,
          }
        : input;
      return (await api.post<LeavePreview>(path, body)).data;
    },
    enabled: input !== null,
    staleTime: 30 * 1000,
  });
}

export function useSubstitutes(
  range: { start: string; end: string } | null,
  onBehalfOf: number | null = null,
) {
  const scope = onBehalfOf ? `user-${onBehalfOf}` : "self";
  return useQuery({
    queryKey: leaveKeys.substitutes(scope, range?.start ?? "", range?.end ?? ""),
    queryFn: async () => {
      if (!range) return [];
      const path = onBehalfOf ? `${ROOT}/approvals/substitutes` : `${ROOT}/substitutes`;
      const params: Record<string, string | number> = {
        start_date: range.start,
        end_date: range.end,
      };
      if (onBehalfOf) params.user_id = onBehalfOf;
      return (await api.get<{ items: SubstituteCandidate[] }>(path, { params })).data.items;
    },
    enabled: range !== null,
    staleTime: 60 * 1000,
  });
}

/**
 * Co zmienia zapis nieobecności poza listami urlopów: godziny w timesheecie
 * (urlop wpisuje i zdejmuje dni — `time_hooks.py`), Płace, „Mój zespół”
 * i kafelek zastępstw. Bez tego „Mój miesiąc” przez `staleTime` pokazywał
 * godziny sprzed zgłoszenia.
 */
const LEAVE_AFFECTS = [
  leaveKeys.all,
  timeKeys.all,
  payrollKeys.all,
  teamKeys.all,
  SUBSTITUTION_QUERY_KEY,
] as const;

function useInvalidateLeave() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all(
      LEAVE_AFFECTS.map((queryKey) => queryClient.invalidateQueries({ queryKey })),
    );
}

export function useSubmitLeave() {
  const invalidate = useInvalidateLeave();
  return useMutation({
    mutationFn: async (input: LeaveInput) =>
      (await api.post<LeaveRequestRow>(`${ROOT}/requests`, input)).data,
    onSuccess: invalidate,
  });
}

export function useCancelMyLeave() {
  const invalidate = useInvalidateLeave();
  return useMutation({
    mutationFn: async (id: string) =>
      (await api.post<LeaveRequestRow>(`${ROOT}/requests/${id}/cancel`)).data,
    onSuccess: invalidate,
  });
}

export function useSetForwardConsent() {
  const invalidate = useInvalidateLeave();
  return useMutation({
    mutationFn: async ({ id, consent }: { id: string; consent: boolean }) =>
      (
        await api.put<LeaveRequestRow>(`${ROOT}/requests/${id}/forward-consent`, {
          consent,
        })
      ).data,
    onSuccess: invalidate,
  });
}

/** Osoba dołącza plik do własnego wniosku (przy składaniu albo później). */
export function useAttachLeaveProof() {
  const invalidate = useInvalidateLeave();
  return useMutation({
    mutationFn: async ({ id, file }: { id: string; file: File }) => {
      const form = new FormData();
      form.append("file", file);
      return (
        await api.post<LeaveRequestRow>(`${ROOT}/requests/${id}/proofs`, form, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: invalidate,
  });
}

/** Osoba usuwa plik, który sama dodała (ślad zostaje w e-teczce). */
export function useRemoveLeaveProof() {
  const invalidate = useInvalidateLeave();
  return useMutation({
    mutationFn: async ({ id, proofId }: { id: string; proofId: number }) =>
      (await api.post<LeaveRequestRow>(`${ROOT}/requests/${id}/proofs/${proofId}/remove`))
        .data,
    onSuccess: invalidate,
  });
}

/** Pobranie pliku: `own` — własny wniosek, `team` — Kadry przy cudzym wniosku. */
export async function downloadLeaveProof(
  requestId: string,
  proof: LeaveProof,
  scope: "own" | "team",
): Promise<void> {
  const base = scope === "own" ? "requests" : "approvals";
  const { blob, filename } = await fetchAuthenticatedDownload(
    `${ROOT}/${base}/${requestId}/proofs/${proof.id}/file`,
  );
  downloadBlob(blob, filename ?? proof.file_name);
}

async function fetchPending(): Promise<PendingLeavePayload> {
  return (await api.get<PendingLeavePayload>(`${ROOT}/approvals/pending`)).data;
}

export function usePendingLeave(enabled = true) {
  return useQuery({
    queryKey: leaveKeys.pending,
    queryFn: fetchPending,
    select: (payload: PendingLeavePayload) => payload.items,
    enabled,
  });
}

/** „W zastępstwie za …” — z tej samej odpowiedzi co kolejka (jedno zapytanie). */
export function useLeaveCovering(enabled = true) {
  return useQuery({
    queryKey: leaveKeys.pending,
    queryFn: fetchPending,
    select: (payload: PendingLeavePayload) => payload.covering ?? [],
    enabled,
  });
}

/** Zgłoszenia z B2B i zlecenia do wiadomości — z tej samej odpowiedzi co kolejka. */
export function useReportedLeave(enabled = true) {
  return useQuery({
    queryKey: leaveKeys.pending,
    queryFn: fetchPending,
    select: (payload: PendingLeavePayload) => payload.reported ?? [],
    enabled,
  });
}

/** Koordynator zgłasza kolizję terminu z pracą (D5) — powiadomienie osoby. */
export function useReportConflict() {
  const invalidate = useInvalidateLeave();
  return useMutation({
    mutationFn: async ({ id, note }: { id: string; note: string }) =>
      (await api.post<LeaveRequestRow>(`${ROOT}/${id}/conflict`, { note })).data,
    onSuccess: invalidate,
  });
}

export interface LeaveHistoryFilters {
  status: LeaveStatus | null;
  user_id: number | null;
}

/** Liczba wniosków per status w zakresie listy (bez filtra statusu). */
export type LeaveStatusCounts = Record<LeaveStatus | "all", number>;

export interface LeaveHistory {
  items: LeaveRequestRow[];
  counts: LeaveStatusCounts | null;
}

export function useLeaveHistory(filters: LeaveHistoryFilters, enabled = true) {
  return useQuery({
    queryKey: leaveKeys.history(filters),
    queryFn: async (): Promise<LeaveHistory> => {
      const params: Record<string, string | number> = { limit: 200 };
      if (filters.status) params.status = filters.status;
      if (filters.user_id) params.user_id = filters.user_id;
      const data = (
        await api.get<{ items: LeaveRequestRow[]; counts?: LeaveStatusCounts }>(
          `${ROOT}/approvals/history`,
          { params },
        )
      ).data;
      return { items: data.items, counts: data.counts ?? null };
    },
    enabled,
  });
}

/** Zmiana cudzego wniosku — tylko pola, które się zmieniły (`null` czyści). */
export interface LeaveEditInput {
  leave_type?: LeaveType;
  start_date?: string;
  end_date?: string;
  half_day?: HalfDay | null;
  substitute_user_id?: number | null;
}

/** Przełożony albo Kadry zmieniają rodzaj, daty, pół dnia albo zastępcę. */
export function useEditLeave() {
  const invalidate = useInvalidateLeave();
  return useMutation({
    mutationKey: [...HR_COUNTS_MUTATION_KEY, "leave-edit"],
    mutationFn: async ({ id, changes }: { id: string; changes: LeaveEditInput }) =>
      (await api.patch<LeaveRequestRow>(`${ROOT}/approvals/${id}`, changes)).data,
    onSuccess: invalidate,
  });
}

/** Kadry wyłączają przekierowanie poczty cudzego wniosku (powód w historii). */
export function useForwardOff() {
  const invalidate = useInvalidateLeave();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, reason }: { id: string; reason: string }) =>
      (await api.post<LeaveRequestRow>(`${ROOT}/approvals/${id}/forward-off`, { reason }))
        .data,
    onSuccess: async () => {
      await invalidate();
      // Lista przekierowań w karcie Microsoft 365 (Ustawienia → Kadry).
      await queryClient.invalidateQueries({ queryKey: ["hr", "m365"] });
    },
  });
}

export function useOnBehalfPeople(enabled = true) {
  return useQuery({
    queryKey: leaveKeys.people,
    queryFn: async () =>
      (await api.get<{ items: OnBehalfPerson[] }>(`${ROOT}/approvals/people`)).data.items,
    enabled,
  });
}

export function useDecideLeave() {
  const invalidate = useInvalidateLeave();
  return useMutation({
    // Licznik „Akceptacji” liczy się od nowa po decyzji.
    mutationKey: [...HR_COUNTS_MUTATION_KEY, "leave-decision"],
    mutationFn: async ({
      id,
      decision,
      note,
    }: {
      id: string;
      decision: "approve" | "reject";
      note?: string;
    }) =>
      (
        await api.post<LeaveRequestRow>(`${ROOT}/approvals/${id}/${decision}`, {
          note: note ?? null,
        })
      ).data,
    onSuccess: invalidate,
  });
}

export function useCancelTeamLeave() {
  const invalidate = useInvalidateLeave();
  return useMutation({
    mutationKey: [...HR_COUNTS_MUTATION_KEY, "leave-cancel"],
    mutationFn: async (id: string) =>
      (await api.post<LeaveRequestRow>(`${ROOT}/approvals/${id}/cancel`)).data,
    onSuccess: invalidate,
  });
}

export function useEnterOnBehalf() {
  const invalidate = useInvalidateLeave();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: OnBehalfInput) =>
      (await api.post<LeaveRequestRow>(`${ROOT}/approvals/on-behalf`, input)).data,
    // Wpis z kartoteki („Dodaj za tę osobę”) — jej lista nieobecności i pula też.
    onSuccess: (_row, input) =>
      Promise.all([
        invalidate(),
        queryClient.invalidateQueries({ queryKey: hrKeys.person(input.user_id) }),
      ]),
  });
}

export function useTeamCalendar(month: string, department: string | null, team: boolean) {
  return useQuery({
    queryKey: leaveKeys.calendar(month, department, team),
    queryFn: async () => {
      const params: Record<string, string | boolean> = { month };
      if (department) params.department = department;
      if (team) params.team = true;
      return (await api.get<TeamCalendar>(`${ROOT}/calendar`, { params })).data;
    },
  });
}

/** „Nieobecni dziś” — górny pasek; odświeżane co 5 minut jak inne liczniki paska. */
export function useAbsentToday(enabled: boolean) {
  return useQuery({
    queryKey: leaveKeys.absentToday,
    queryFn: async () =>
      (
        await api.get<{ date: string; items: AbsentTodayRow[]; total: number }>(
          `${ROOT}/absent-today`,
        )
      ).data,
    enabled,
    staleTime: WS_BACKED_SAFETY_POLL_MS,
    refetchInterval: WS_BACKED_SAFETY_POLL_MS,
  });
}

/**
 * Czy moduł urlopów jest otwarty dla zalogowanej osoby — plakietki przy
 * osobach poza ekranami „Ludzi” (lista „@”, lista rekrutacji). Praktykant ma
 * własną powłokę i nie pyta o moduły (jak „Nieobecni dziś” w pasku). Awaria
 * zapytania = zamknięty: plakietka to dodatek, nie warunek działania ekranu.
 */
export function useLeaveModuleOpen(enabled = true): boolean {
  const user = useAuthStore((state) => state.user);
  const roles = new Set([user?.role, ...(user?.roles ?? [])].filter(Boolean));
  const traineeOnly = roles.size === 1 && roles.has("trainee");
  const config = useHrConfig(enabled && Boolean(user) && !traineeOnly);
  return enabled && Boolean(config.data?.open_modules?.leave);
}

/**
 * Nieobecności wielu osób naraz (plakietka przy osobie w listach).
 * Jedno zapytanie na listę, nie na wiersz; klucz z posortowanych id.
 */
export function useAbsences(userIds: readonly number[], options?: { on?: string; enabled?: boolean }) {
  const ids = Array.from(new Set(userIds.filter((id) => Number.isInteger(id) && id > 0)))
    .sort((a, b) => a - b)
    .slice(0, 300);
  const joined = ids.join(",");
  const on = options?.on ?? null;
  const query = useQuery({
    queryKey: leaveKeys.absence(joined, on),
    queryFn: async () => {
      const params: Record<string, string> = { user_ids: joined };
      if (on) params.on = on;
      return (
        await api.get<{ on: string; items: PersonAbsence[] }>(`${ROOT}/absence`, { params })
      ).data;
    },
    enabled: (options?.enabled ?? true) && ids.length > 0,
    staleTime: 5 * 60 * 1000,
  });
  const byUser = new Map<number, PersonAbsence>();
  for (const item of query.data?.items ?? []) byUser.set(item.user_id, item);
  return { ...query, byUser };
}
