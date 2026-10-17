/**
 * Dane harnessu `/preview/hr-onboarding` (makieta 14 „Wejście nowej osoby”).
 *
 * Kacper zaczyna pierwszego dnia roboczego PRZYSZŁEGO miesiąca (makieta:
 * pon 2.11 przy dzisiejszym październiku). Terminy zadań w dniach roboczych
 * od startu, jak liczy serwer. Zadania odpowiadają makiecie: zestaw z
 * ewidencji (recepcja), konto M365 (IT), mail powitalny, check-iny 1/7/30.
 */

import type { EmploymentType } from "@/lib/api/hr";
import {
  lifecycleKeys,
  type LifecycleCase,
  type LifecycleTask,
  type LifecycleTemplate,
  type PreviewTask,
} from "@/lib/api/hr-lifecycle";
import { warsawToday } from "@/lib/warsaw-date";
import { shiftMonth } from "@/lib/date-pl";

import { HR_CAST, nthWorkDay, type HarnessPerson } from "../hr-fixtures";
import { addWorkDays } from "../hr-person/fixtures";

const { kacper, marta, paulina, zofia } = HR_CAST;

export const ONBOARDING_CASE_ID = 4401;
export const ONBOARDING_DRAFT_ID = 4402;

export interface OnboardingScene {
  today: string;
  start: string;
}

export function onboardingScene(): OnboardingScene {
  const today = warsawToday();
  return { today, start: nthWorkDay(shiftMonth(today.slice(0, 7), 1), 1) };
}

export const ONBOARDING_TEMPLATES: LifecycleTemplate[] = [
  {
    id: 41,
    kind: "onboarding",
    name: "Wejście — biuro, Rekrutacja IT",
    is_active: true,
    employment_type: "b2b",
    department: "Rekrutacja IT",
    items: [],
  },
  {
    id: 42,
    kind: "onboarding",
    name: "Wejście — podstawowa",
    is_active: true,
    employment_type: null,
    department: null,
    items: [],
  },
];

interface TaskSpec extends PreviewTask {
  who: HarnessPerson | null;
}

/** Zadania wejścia z terminami w dniach roboczych od startu. */
function taskSpecs(start: string): TaskSpec[] {
  return [
    { title: "Konto Microsoft 365 i licencja", category: "accounts", assignee_kind: "it", who: null, due_date: addWorkDays(start, -2) },
    { title: "Wydaj zestaw biura z ewidencji: laptop, monitor, słuchawki", category: "equipment", assignee_kind: "reception", who: zofia, due_date: addWorkDays(start, -2) },
    { title: "Karta dostępu: ogólny + biuro, pon–pt 7–19", category: "equipment", assignee_kind: "reception", who: zofia, due_date: addWorkDays(start, -2) },
    { title: "Mail powitalny z planem pierwszego dnia", category: "documents", assignee_kind: "people_admin", who: paulina, due_date: addWorkDays(start, -1) },
    { title: "Protokół wydania sprzętu do podpisu w biurze", category: "documents", assignee_kind: "reception", who: zofia, due_date: start },
    { title: "Check-in z przełożoną — dzień 1", category: "meeting", assignee_kind: "manager", who: marta, due_date: start },
    { title: "Check-in z przełożoną — dzień 7", category: "meeting", assignee_kind: "manager", who: marta, due_date: addWorkDays(start, 4) },
    { title: "Check-in z przełożoną — dzień 30", category: "meeting", assignee_kind: "manager", who: marta, due_date: addWorkDays(start, 21) },
  ];
}

/** `POST /api/hr/lifecycle/preview` — podgląd zadań w kroku „Zadania”. */
export function previewTasks(start: string, templateId: number | null) {
  const template = ONBOARDING_TEMPLATES.find((t) => t.id === templateId) ?? ONBOARDING_TEMPLATES[0];
  return {
    template_id: template.id,
    template_name: template.name,
    tasks: taskSpecs(start).map(({ title, category, assignee_kind, due_date }) => ({
      title,
      category,
      assignee_kind,
      due_date,
    })),
  };
}

/**
 * Klucze podglądu dla daty startu ze sceny: każda forma zatrudnienia, dział
 * pusty albo „Rekrutacja IT”, lista dobrana albo wskazana — kliknięcie przez
 * kreator z tą datą nie wysyła zapytania.
 */
export function previewSeeds(start: string) {
  const types: EmploymentType[] = ["b2b", "uop", "zlecenie"];
  const departments = [null, "Rekrutacja IT"];
  const templates = [null, ...ONBOARDING_TEMPLATES.map((t) => t.id)];
  return types.flatMap((employment_type) =>
    departments.flatMap((department) =>
      templates.map((template_id) => ({
        key: lifecycleKeys.preview({
          kind: "onboarding",
          anchor: start,
          template_id,
          employment_type,
          department,
        }),
        data: previewTasks(start, template_id),
      })),
    ),
  );
}

/** Konta bez kartoteki (krok 1 „Osoba i konto”). */
export const ACCOUNTS_WITHOUT_PROFILE = [kacper].map((person) => ({
  user_id: person.id,
  name: person.name,
  email: person.email,
}));

function task(id: number, spec: TaskSpec, done: boolean, today: string): LifecycleTask {
  return {
    id,
    title: spec.title,
    category: spec.category,
    assignee_kind: spec.assignee_kind,
    assignee_user_id: spec.who?.id ?? null,
    assignee_name: spec.who?.name ?? null,
    due_date: spec.due_date,
    status: done ? "done" : "open",
    overdue: false,
    done_at: done ? `${today}T10:00:00Z` : null,
    done_by_name: done ? "Dział IT" : null,
    note: null,
    from_template: true,
    can_toggle: true,
  };
}

/** Sprawa wejścia: `active` (konto jest, M365 zrobione) albo `draft` bez konta. */
export function onboardingCase(scene: OnboardingScene, status: "active" | "draft"): LifecycleCase {
  const active = status === "active";
  const tasks = taskSpecs(scene.start).map((spec, index) =>
    task(4500 + index, spec, active && index === 0, scene.today),
  );
  const done = tasks.filter((row) => row.status !== "open").length;
  return {
    id: active ? ONBOARDING_CASE_ID : ONBOARDING_DRAFT_ID,
    kind: "onboarding",
    status,
    user_id: active ? kacper.id : null,
    person_name: kacper.name,
    pending_email: active ? null : kacper.email,
    template_id: 41,
    template_name: ONBOARDING_TEMPLATES[0].name,
    start_date: scene.start,
    last_working_day: null,
    deactivate_on: null,
    handover_at: null,
    manager_user_id: marta.id,
    manager_name: marta.name,
    owner_name: paulina.name,
    started_at: active ? `${scene.today}T08:00:00Z` : null,
    handover_executed_at: null,
    account_closed_at: null,
    account_close_result: null,
    completed_at: null,
    cancelled_at: null,
    scope: "admin",
    can_manage: true,
    can_cancel: true,
    tasks,
    progress: { done, total: tasks.length, overdue: 0 },
    profile_values: {
      employment_type: "b2b",
      job_title: "Rekruter",
      department: "Rekrutacja IT",
      default_location: "onsite",
      timesheet_required: true,
      can_log_overtime: false,
      manager_user_id: marta.id,
      work_start_date: scene.start,
    },
  };
}
