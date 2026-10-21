// Kartoteka → „Nieobecności i godziny” (przebudowa „Ludzi”, 22.10.2026).
//
// Lustro `GET /api/hr/people/{id}/history` (`backend/app/api/hr_people.py`,
// `services/hr/person_history.py`): nieobecności osoby w roku i jej raporty
// godzin z ostatnich 6 miesięcy. Krąg = pełna kartoteka (osoba, koordynator,
// Kadry, Finanse, admin); rodzaj nieobecności tylko dla kręgu D6 — reszta
// dostaje „Nieobecność” i tylko zatwierdzone. Część modułu zamkniętego dla
// patrzącego to `null`, nie pusta lista.

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

import { hrKeys } from "./hr";
import type { HalfDay, LeaveType } from "./hr-leave";
import type { TimesheetStatus } from "./hr-time";

/** Stan nieobecności na liście kartoteki. */
export type AbsenceState = "planned" | "waiting" | "used" | "rejected";

export interface PersonAbsence {
  id: string;
  start_date: string;
  end_date: string;
  half_day: HalfDay | null;
  days_total: string;
  status: "approved" | "pending" | "rejected";
  state: AbsenceState;
  /** `null` poza kręgiem D6. */
  leave_type: LeaveType | null;
  /** Rodzaj w słowach formy albo „Nieobecność”. */
  label: string;
}

export interface PersonTimesheetMonth {
  year: number;
  month: number;
  /** `null` = miesiąc w zatrudnieniu bez raportu („nie założony”). */
  timesheet_id: number | null;
  status: TimesheetStatus | null;
  hours: number;
  norm_hours: number;
  has_pdf: boolean;
}

export interface PersonHistory {
  year: number;
  today: string;
  absences: { type_visible: boolean; items: PersonAbsence[] } | null;
  timesheets: {
    timesheet_required: boolean;
    items: PersonTimesheetMonth[];
  } | null;
}

/** Klucz pod `hrKeys.person` — zapis kartoteki odświeża też historię. */
export const personHistoryKey = (userId: number, year: number) =>
  [...hrKeys.person(userId), "history", year] as const;

export function usePersonHistory(userId: number, year: number, enabled = true) {
  return useQuery({
    queryKey: personHistoryKey(userId, year),
    queryFn: async () =>
      (
        await api.get<PersonHistory>(`/api/hr/people/${userId}/history`, {
          params: { year },
        })
      ).data,
    enabled,
  });
}
