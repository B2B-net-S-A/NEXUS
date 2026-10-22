/**
 * Fikcyjny katalog „Ludzi” i rozjazdy kartoteka ↔ konto do harnessów
 * (`/preview/hr-people`, `/preview/hr-structure`).
 */

import type { AccountMismatches, Person, PersonFull, PersonToday } from "@/lib/api/hr";
import { warsawToday } from "@/lib/warsaw-date";

import { HR_CAST } from "../hr-fixtures";
import { harnessDirectory } from "../hr-person/fixtures";

const { kacper, julia, marta } = HR_CAST;

function plusDays(days: number): string {
  const [y, m, d] = warsawToday().split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

/** Stan „Dziś” per osoba (bez rodzaju nieobecności — jak serwer, D6). */
const TODAY: Partial<Record<number, PersonToday>> = {
  [HR_CAST.ewa.id]: {
    absent_until: plusDays(2),
    half_day: null,
    substitute_name: HR_CAST.ola.name,
    presence: null,
  },
  [HR_CAST.julia.id]: { absent_until: plusDays(2), half_day: null, substitute_name: null, presence: null },
  [HR_CAST.kamil.id]: {
    absent_until: plusDays(1),
    half_day: null,
    substitute_name: HR_CAST.ola.name,
    presence: null,
  },
  [HR_CAST.tomasz.id]: { absent_until: null, half_day: null, substitute_name: null, presence: "business_trip" },
  [HR_CAST.adam.id]: { absent_until: null, half_day: null, substitute_name: null, presence: "remote" },
};

/** Forma (widzą ją tylko Finanse i admin) i staż — fikcyjne. */
const FORMS: Partial<Record<number, Pick<PersonFull, "employment_type" | "student_contribution_exempt">>> = {
  [HR_CAST.marta.id]: { employment_type: "uop" },
  [HR_CAST.julia.id]: { employment_type: "zlecenie", student_contribution_exempt: true },
  [HR_CAST.adam.id]: { employment_type: "zlecenie", student_contribution_exempt: true },
  [HR_CAST.admin.id]: { employment_type: "uop" },
  [HR_CAST.paulina.id]: { employment_type: "uop" },
  [HR_CAST.zofia.id]: { employment_type: "zlecenie" },
};

const STARTS: Partial<Record<number, string>> = {
  [HR_CAST.marta.id]: "2024-09-02",
  [HR_CAST.ewa.id]: "2025-10-01",
  [HR_CAST.julia.id]: "2026-02-02",
  [HR_CAST.ola.id]: "2025-03-03",
  [HR_CAST.tomasz.id]: "2025-10-06",
  [HR_CAST.kamil.id]: "2023-09-04",
  [HR_CAST.adam.id]: "2026-04-01",
  [HR_CAST.natalia.id]: "2025-10-13",
  [HR_CAST.admin.id]: "2022-05-02",
  [HR_CAST.paulina.id]: "2024-09-16",
  [HR_CAST.zofia.id]: "2025-10-01",
  [HR_CAST.piotr.id]: "2024-10-01",
};

/** Pełne wiersze katalogu — Kadry bez Płac dostają je bez formy umowy. */
function fullRows(withForm: boolean): Person[] {
  return harnessDirectory({ [HR_CAST.tomasz.id]: "offboarding" }).items.map(
    (card): PersonFull => ({
      ...card,
      scope: "full",
      employment_type: withForm ? (FORMS[card.user_id]?.employment_type ?? "b2b") : null,
      ...(withForm
        ? { student_contribution_exempt: FORMS[card.user_id]?.student_contribution_exempt ?? false }
        : {}),
      employment_type_pending: false,
      hired_on: null,
      work_start_date: STARTS[card.user_id] ?? null,
      last_working_day: card.user_id === HR_CAST.tomasz.id ? "2026-11-30" : null,
      timesheet_required: card.user_id !== HR_CAST.natalia.id,
      can_log_overtime: false,
      roles: ["recruiter"],
      today: TODAY[card.user_id] ?? null,
    }),
  );
}

export function harnessPeopleDirectory(withForm: boolean): { items: Person[]; total: number } {
  const kacperRow: PersonFull = {
    user_id: kacper.id,
    name: kacper.name,
    email: kacper.email,
    job_title: null,
    department: "Administracja",
    phone: null,
    default_location: "onsite",
    employment_status: "pending",
    manager_user_id: null,
    manager_name: null,
    scope: "full",
    employment_type: withForm ? "b2b" : null,
    employment_type_pending: true,
    manager_pending: true,
    hired_on: null,
    work_start_date: plusDays(16),
    last_working_day: null,
    timesheet_required: true,
    can_log_overtime: false,
    roles: ["recruiter"],
    today: null,
  };
  const items = [...fullRows(withForm), kacperRow].sort((a, b) =>
    a.name.localeCompare(b.name, "pl"),
  );
  return { items, total: items.length };
}

/** Wizytówki dla rekruterki: bez formy i dat, z kolumną „Dziś”. */
export function harnessPeopleCards(): { items: Person[]; total: number } {
  const base = harnessDirectory({ [HR_CAST.tomasz.id]: "offboarding" });
  return {
    ...base,
    items: base.items.map((card) => ({ ...card, today: TODAY[card.user_id] ?? null })),
  };
}

export const HARNESS_MISMATCHES: AccountMismatches = {
  items: [
    {
      user_id: marta.id,
      name: marta.name,
      email: marta.email,
      account_active: false,
      employment_status: "active",
      proposed_status: "exited",
      last_working_day: null,
      proposed_last_working_day: "2026-10-10",
      kind: "exit",
      reports: 2,
    },
    {
      user_id: julia.id,
      name: julia.name,
      email: julia.email,
      account_active: true,
      employment_status: "exited",
      proposed_status: "active",
      last_working_day: "2026-08-31",
      proposed_last_working_day: null,
      kind: "return",
      reports: 0,
    },
    {
      user_id: 9001,
      name: "Igor Bezkartoteczny",
      email: "igor@example.com",
      account_active: true,
      employment_status: null,
      proposed_status: "active",
      last_working_day: null,
      proposed_last_working_day: null,
      kind: "missing",
      reports: 0,
    },
  ],
  total: 3,
  pending: { employment_type: 1, manager: 1 },
};
