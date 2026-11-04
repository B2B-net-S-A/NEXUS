// „Ludzie → Mój zespół” (etap 2, D6, 17.10.2026) — przełożony o swoich ludziach.
//
// Lustro `backend/app/api/hr_team.py`. Bez stawek (D2): premie z kwotą, ale bez
// stawek godzinowych i danych reguły. Pole `null` = moduł wyłączony albo brak
// prawa („nie dotyczy”), nigdy „zero”.

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { EmploymentStatus, EmploymentType } from "@/lib/api/hr";
import type { QueueStatus } from "@/lib/api/hr-time";

/** Status timesheetu z kolejki akceptacji (ten sam słownik co „Mój miesiąc”). */
export type TeamTimesheetStatus = QueueStatus;

export interface TeamToday {
  absent: boolean;
  until?: string;
  half_day?: string | null;
  leave_type?: string | null;
  leave_type_label?: string;
  substitute_name?: string | null;
}

export interface TeamLeave {
  has_pool: boolean;
  /** Pula z dniami płatnymi (> 0) — to samo co w `GET /api/hr/leave/balance`. */
  has_paid_pool: boolean;
  remaining_days: string | null;
  planned_days: string;
  pending_days: string;
}

export interface TeamMonthRow {
  hours: number;
  status: TeamTimesheetStatus;
  timesheet_id: number | null;
  /** Dni robocze przed dziś bez wpisu (szkic albo brak raportu), ISO. */
  missing_dates?: string[];
}

export interface TeamBonusItem {
  id: number;
  amount: string;
  currency: string;
  category_label: string;
  status: "proposed" | "assigned" | "cancelled";
  period_year: number;
  period_month: number;
  eligible_on: string | null;
  description: string | null;
}

export interface TeamBonuses {
  count: number;
  proposals: number;
  totals: { currency: string; amount: string }[];
  items: TeamBonusItem[];
}

export interface TeamLeaveDecision {
  id: string;
  start_date: string;
  end_date: string;
  half_day: string | null;
  leave_type_label: string;
  days_total: string;
  /** Chwila złożenia (do „czeka N dni”); starszy serwer jej nie wysyła. */
  created_at?: string | null;
}

export interface TeamTimesheetDecision {
  id: number;
  year: number;
  month: number;
  link: string;
  submitted_at?: string | null;
}

/**
 * Stan dnia w mini-tygodniu (pn–pt, 19.10.2026) — bez rodzaju nieobecności (D6).
 * `pending` = wniosek czeka (tylko krąg D6), `off` = święto albo dzień wolny firmy.
 */
export type TeamWeekState =
  | "work"
  | "off"
  | "absent"
  | "pending"
  | "business_trip"
  | "remote"
  // Urlopy zamknięte dla patrzącego: nieobecności nie są czytane, więc dzień
  // bez wpisu w „Moim miesiącu” nie jest „w pracy” (audyt 21.10.2026).
  | "unknown";

export interface TeamWeekDay {
  date: string;
  state: TeamWeekState;
  half_day: string | null;
}

export interface TeamPerson {
  user_id: number;
  name: string;
  job_title: string | null;
  /** `null` — Kadry bez Płac oglądające cudzy zespół formy nie dostają (19.10.2026). */
  employment_type: EmploymentType | null;
  employment_type_pending?: boolean;
  /** Uczeń/student na zleceniu (D8) — sam znacznik; daty widzą osoba i Płace. */
  student?: boolean | null;
  employment_status: EmploymentStatus;
  last_working_day: string | null;
  today: TeamToday | null;
  covering_for: string[];
  /** Pn–pt bieżącego tygodnia; `null` — urlopy i czas zamknięte. */
  week?: TeamWeekDay[] | null;
  leave: TeamLeave | null;
  month: TeamMonthRow | null;
  timesheet_required: boolean;
  bonuses: TeamBonuses | null;
  to_decide: {
    leave_requests: TeamLeaveDecision[];
    timesheets: TeamTimesheetDecision[];
  };
}

export interface MyTeam {
  manager: { user_id: number; name: string };
  is_own: boolean;
  today: string;
  modules: { leave: boolean; time: boolean; payroll: boolean };
  sees_bonuses: boolean;
  month: { year: number; month: number; norm_hours: number; deadline: string } | null;
  /** Dni mini-tygodnia (pn–pt) z rodzajem dnia w kalendarzu firmy. */
  week?: { days: { date: string; kind: "work" | "weekend" | "holiday" | "company" }[] } | null;
  people: TeamPerson[];
  stats: {
    people: number;
    absent_today: number;
    leave_requests: number;
    timesheets: number;
    bonus_proposals: number | null;
  };
}

export interface TeamManager {
  user_id: number;
  name: string;
  reports: number;
}

const BASE = "/api/hr/team";

export const teamKeys = {
  all: ["hr", "team"] as const,
  team: (managerId: number | null) => ["hr", "team", managerId] as const,
  managers: ["hr", "team", "managers"] as const,
};

/** `managerId` = `null` — własny zespół; liczba — zespół innego przełożonego (Kadry). */
export function useMyTeam(managerId: number | null, enabled = true) {
  return useQuery({
    queryKey: teamKeys.team(managerId),
    queryFn: async () =>
      (
        await api.get<MyTeam>(BASE, {
          params: managerId ? { manager: managerId } : undefined,
        })
      ).data,
    enabled,
  });
}

export function useTeamManagers(enabled: boolean) {
  return useQuery({
    queryKey: teamKeys.managers,
    queryFn: async () => (await api.get<{ items: TeamManager[] }>(`${BASE}/managers`)).data.items,
    enabled,
    staleTime: 60 * 1000,
  });
}
