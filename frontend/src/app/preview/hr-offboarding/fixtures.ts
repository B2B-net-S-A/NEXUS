/**
 * Dane harnessu `/preview/hr-offboarding` (makieta 8 „Odejście”).
 *
 * Tomasz odchodzi; ostatni dzień to ostatni dzień roboczy PRZYSZŁEGO miesiąca
 * (makieta: pon 30.11 przy dzisiejszym październiku), konto wyłącza się dzień
 * później, przekazanie pracy o 18:00 ostatniego dnia — jak liczy serwer.
 * Wiersze „Co osoba ma w NEXUSIE” mają etykiety i uwagi serwera
 * (`backend/app/services/hr/handover.py`, `WORK_KINDS`); liczby zmyślone.
 */

import { shiftMonth, warsawToday } from "@/components/hr/leave/leave-format";
import type { PersonFull } from "@/lib/api/hr";
import type {
  LifecycleCase,
  LifecycleTask,
  LifecycleTemplate,
  TransferKind,
  WorkKind,
  WorkRow,
} from "@/lib/api/hr-lifecycle";

import { HR_CAST, harnessWorkDays, shiftDay, type HarnessPerson } from "../hr-fixtures";
import { addWorkDays, personCard, warsawMomentIso } from "../hr-person/fixtures";

const { tomasz, ola, ewa, marta, paulina, zofia } = HR_CAST;

export const OFFBOARDING_CASE_ID = 4201;

export const TRANSFER_KINDS: TransferKind[] = [
  "recruitments",
  "my_people",
  "delivery_lead_jobs",
  "dl_clients",
];

export interface OffboardingScene {
  today: string;
  lastDay: string;
  deactivateOn: string;
}

export function offboardingScene(): OffboardingScene {
  const today = warsawToday();
  const next = shiftMonth(today.slice(0, 7), 1);
  const lastDay = harnessWorkDays(next).at(-1) ?? `${next}-28`;
  // Konto wyłącza się dzień po ostatnim dniu pracy (makieta: 1.12 00:00).
  return { today, lastDay, deactivateOn: shiftDay(lastDay, 1) };
}

export function tomaszProfile(scene: OffboardingScene | null): PersonFull {
  return {
    ...personCard(tomasz, scene ? "offboarding" : "active"),
    scope: "full",
    employment_type: "b2b",
    hired_on: "2024-06-03",
    work_start_date: "2024-06-03",
    last_working_day: scene?.lastDay ?? null,
    timesheet_required: true,
    can_log_overtime: false,
    roles: ["recruiter"],
  };
}

interface WorkSpec {
  kind: WorkKind;
  label: string;
  note: string;
  transferable: boolean;
  count: number;
}

const WORK: WorkSpec[] = [
  { kind: "recruitments", label: "Rekrutacje, w których pracuje jako rekruter", transferable: true, count: 4, note: "Przejmujący wchodzi do zespołu rekrutacji, odchodzący z niego schodzi." },
  { kind: "pipeline_cards", label: "Karty w procesie", transferable: false, count: 11, note: "Idą z rekrutacjami." },
  { kind: "client_meetings", label: "Rozmowy u klienta po ostatnim dniu", transferable: false, count: 2, note: "Idą z rekrutacjami — termin zostaje w kalendarzu rekrutacji." },
  { kind: "followups", label: "Umówione kontakty z kandydatami", transferable: false, count: 3, note: "Kandydaci prosili o telefon po ostatnim dniu — idą z rekrutacjami." },
  { kind: "my_people", label: "„Moi ludzie”", transferable: true, count: 37, note: "Osoby trafiają na listę przejmującego jako przypięte." },
  { kind: "delivery_lead_jobs", label: "Rekrutacje, w których jest Delivery Leadem", transferable: true, count: 0, note: "Przejmujący zostaje Delivery Leadem tych rekrutacji." },
  { kind: "dl_clients", label: "Klienci Delivery Leada", transferable: true, count: 0, note: "Przejmujący dostaje klientów do portfela (główny opiekun zostaje główny)." },
  { kind: "substitutions", label: "Zastępstwa w urlopach po ostatnim dniu", transferable: false, count: 1, note: "Zastępcę zmienia osoba na urlopie albo Kadry we wniosku." },
];

function workRows(receivers: Partial<Record<TransferKind, HarnessPerson>>): WorkRow[] {
  return WORK.map((spec): WorkRow => {
    const receiver = receivers[spec.kind as TransferKind];
    return {
      kind: spec.kind,
      label: spec.label,
      note: spec.note,
      transferable: spec.transferable,
      count: spec.count,
      receiver_user_id: receiver?.id ?? null,
      receiver_name: receiver?.name ?? null,
      status: receiver ? "planned" : null,
      planned_count: receiver ? spec.count : null,
      result: null,
      error: null,
    };
  });
}

interface TaskSpec {
  title: string;
  category: LifecycleTask["category"];
  assignee: LifecycleTask["assignee_kind"];
  who: HarnessPerson | null;
  due: string;
  done?: { by: HarnessPerson; at: string };
  note?: string;
}

function task(id: number, spec: TaskSpec): LifecycleTask {
  return {
    id,
    title: spec.title,
    category: spec.category,
    assignee_kind: spec.assignee,
    assignee_user_id: spec.who?.id ?? null,
    assignee_name: spec.who?.name ?? null,
    due_date: spec.due,
    status: spec.done ? "done" : "open",
    overdue: false,
    done_at: spec.done?.at ?? null,
    done_by_name: spec.done?.by.name ?? null,
    note: spec.note ?? null,
    from_template: true,
    can_toggle: true,
  };
}

/** Zadania z listy odejścia: 2 z 6 zrobione (makieta: „Sprzęt i zadania (2/6)”). */
function tasks(scene: OffboardingScene, started: boolean): LifecycleTask[] {
  const { lastDay, today } = scene;
  const doneAt = `${today}T09:15:00Z`;
  const specs: TaskSpec[] = [
    { title: "Rozmowa wyjściowa z przełożoną", category: "meeting", assignee: "manager", who: marta, due: addWorkDays(lastDay, -10), done: started ? { by: marta, at: doneAt } : undefined },
    { title: "Rozliczenie urlopu", category: "documents", assignee: "people_admin", who: paulina, due: addWorkDays(lastDay, -5), done: started ? { by: paulina, at: doneAt } : undefined },
    { title: "Ostatni timesheet", category: "documents", assignee: "person", who: tomasz, due: lastDay },
    { title: "Zwrot sprzętu: 4 pozycje z ewidencji", category: "equipment", assignee: "reception", who: zofia, due: lastDay, note: "Protokół zwrotu z listy sprzętu osoby." },
    { title: "Dezaktywacja karty dostępu w budynku", category: "equipment", assignee: "reception", who: zofia, due: lastDay },
    { title: "Wyłączenie skrzynki i licencji M365", category: "accounts", assignee: "it", who: null, due: lastDay },
  ];
  return specs.map((spec, index) => task(4300 + index, spec));
}

/** Sprawa odejścia: `active` (rozpoczęta, przejmujący wskazani) albo `draft`. */
export function offboardingCase(scene: OffboardingScene, status: "active" | "draft"): LifecycleCase {
  const started = status === "active";
  const list = tasks(scene, started);
  const done = list.filter((row) => row.status !== "open").length;
  return {
    id: OFFBOARDING_CASE_ID,
    kind: "offboarding",
    status,
    user_id: tomasz.id,
    person_name: tomasz.name,
    pending_email: null,
    template_id: 31,
    template_name: "Odejście — B2B, Rekrutacja IT",
    start_date: null,
    last_working_day: scene.lastDay,
    deactivate_on: scene.deactivateOn,
    handover_at: warsawMomentIso(scene.lastDay, 18),
    manager_user_id: marta.id,
    manager_name: marta.name,
    owner_name: paulina.name,
    started_at: started ? `${scene.today}T08:00:00Z` : null,
    handover_executed_at: null,
    account_closed_at: null,
    account_close_result: null,
    completed_at: null,
    cancelled_at: null,
    scope: "admin",
    can_manage: true,
    can_cancel: true,
    tasks: list,
    progress: { done, total: list.length, overdue: 0 },
    exit_initiator: "employee",
    exit_reason: null,
    exit_note: null,
    work: workRows(started ? { recruitments: ola, my_people: ewa } : { recruitments: marta, my_people: marta }),
  };
}

/** Lista „Przekaż do” z serwera — osoby z rolą, której wymaga ta praca. */
export function receiversFor(kind: TransferKind): { user_id: number; name: string }[] {
  const people =
    kind === "delivery_lead_jobs" || kind === "dl_clients"
      ? [HR_CAST.kamil, HR_CAST.adam]
      : [ola, ewa, HR_CAST.julia, marta];
  return people.map((person) => ({ user_id: person.id, name: person.name }));
}

/** Aktywne listy zadań odejścia (formularz „Lista zadań”). */
export const OFFBOARDING_TEMPLATES: LifecycleTemplate[] = [
  {
    id: 31,
    kind: "offboarding",
    name: "Odejście — B2B, Rekrutacja IT",
    is_active: true,
    employment_type: "b2b",
    department: "Rekrutacja IT",
    items: [],
  },
  {
    id: 32,
    kind: "offboarding",
    name: "Odejście — podstawowa",
    is_active: true,
    employment_type: null,
    department: null,
    items: [],
  },
];
