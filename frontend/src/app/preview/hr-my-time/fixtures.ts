/**
 * Dane harnessu „Mój czas” (`/preview/hr-my-time`) — wyłącznie fikcyjne.
 *
 * Miesiąc i „dziś” liczymy z zegara przeglądarki tymi samymi funkcjami co
 * ekran (`warsawToday`, `currentYearMonth`), więc klucze zapytań trafiają
 * w zasiew niezależnie od dnia otwarcia harnessu.
 */

import { LEAVE_TYPE_LABELS } from "@/components/hr/leave/leave-format";
import type { EmploymentType, OwnProfile } from "@/lib/api/hr";
import type { HolderEquipment } from "@/lib/api/equipment";
import type { ApprovalRequestRow } from "@/lib/api/hr-approvals";
import type {
  LeaveBalance,
  LeavePreview,
  LeaveRequestRow,
  SubstituteCandidate,
} from "@/lib/api/hr-leave";
import type { BonusForecast, BonusRow, MyPayroll, MySettlement, RateRow } from "@/lib/api/hr-payroll";
import type {
  DayHint,
  MonthDay,
  MonthView,
  TimesheetEntry,
  TimesheetHistoryItem,
  TimesheetTemplate,
} from "@/lib/api/hr-time";
import { monthYearPl, shiftMonth, type YearMonth } from "@/lib/date-pl";
import { warsawToday } from "@/lib/warsaw-date";

import {
  HR_CAST,
  HR_CLIENTS,
  harnessMonthDays,
  harnessWorkDays,
  shiftDay,
  type HarnessPerson,
} from "../hr-fixtures";

const { ola, kamil, ewa, adam, marta, julia, tomasz } = HR_CAST;
const { bank, telecom, clinic } = HR_CLIENTS;

const isoMonth = ({ year, month }: YearMonth) => `${year}-${String(month).padStart(2, "0")}`;

// ── Kartoteka ───────────────────────────────────────────────────────────────

export function myProfile(
  person: HarnessPerson,
  year: number,
  form: EmploymentType = "b2b",
): { has_profile: true } & OwnProfile {
  return {
    has_profile: true,
    user_id: person.id,
    name: person.name,
    email: person.email,
    job_title: person.jobTitle,
    department: person.department,
    phone: null,
    default_location: "onsite",
    employment_status: "active",
    manager_user_id: marta.id,
    manager_name: marta.name,
    scope: "full",
    employment_type: form,
    employment_type_pending: false,
    hired_on: "2025-03-03",
    work_start_date: "2025-03-03",
    last_working_day: null,
    timesheet_required: true,
    can_log_overtime: true,
    roles: person.roles ?? [person.role],
    entitlements:
      form === "zlecenie"
        ? []
        : [
            {
              year,
              entitlement_days: form === "uop" ? "26" : "24",
              carried_over_days: "2",
              used_initial_days: "0",
            },
          ],
  };
}

export const MY_EQUIPMENT: HolderEquipment = {
  active: [
    {
      assignment_id: 501,
      item_id: 153,
      category: "laptop",
      model_name: "Dell Latitude 5520",
      inventory_number: "153",
      serial_number: "SN-TEST-0153",
      imei: null,
      phone_number: null,
      access_card_number: null,
      ownership: "nasz",
      item_status: "wydany",
      holder: { kind: "user", id: ola.id, name: ola.name, client_name: null },
      issued_at: "2025-03-03",
      returned_at: null,
      return_condition: null,
      return_notes: null,
      issue_protocol: "PZO/TEST/2025/006",
      issue_protocol_id: 6,
      return_protocol: null,
      return_protocol_id: null,
      unit_value: "3200.00",
    },
  ],
  history: [],
  protocols: [
    { id: 6, number: "PZO/TEST/2025/006", kind: "wydanie", status: "potwierdzony", protocol_date: "2025-03-03" },
    // Zwrot ładowarki czeka na podpis linkiem — „Przegląd → Do zrobienia”.
    { id: 11, number: "PZO/TEST/2026/011", kind: "zwrot", status: "oczekuje", protocol_date: "2026-10-20" },
  ],
};

/** Moje zadanie z wejścia nowej osoby (wykonawca: Ola) — „Do zrobienia”. */
export function myLifecycleTasks(today: string) {
  return [
    {
      task_id: 71,
      case_id: 7,
      kind: "onboarding" as const,
      person_name: "Adam Wzorcowy",
      title: "Szkolenie stanowiskowe: praca w NEXUSIE",
      due_date: shiftDay(today, 2),
      overdue: false,
      link: "/people/onboarding/7",
    },
  ];
}

// ── Urlopy ──────────────────────────────────────────────────────────────────

export function balance(year: number, remaining: string, approved: string): LeaveBalance {
  return {
    year,
    employment_type: "b2b",
    has_pool: true,
    has_paid_pool: true,
    entitlement_days: "26",
    carried_over_days: "2",
    used_initial_days: "0",
    as_of: `${year}-10-22`,
    approved_days: approved,
    used_days: approved,
    planned_days: "0",
    pending_days: "0",
    unpaid_days: "0",
    remaining_days: remaining,
    on_demand_used: null,
    on_demand_limit: null,
    childcare_used: null,
    childcare_limit: null,
    // B2B i zlecenie widzą tylko urlop z puli (reguła z Compassa).
    allowed_types: ["vacation"],
  };
}

function request(
  id: string,
  person: HarnessPerson,
  start: string,
  end: string,
  days: string,
  status: LeaveRequestRow["status"],
  extra: Partial<LeaveRequestRow> = {},
): LeaveRequestRow {
  return {
    id,
    user_id: person.id,
    user_name: person.name,
    leave_type: "vacation",
    leave_type_label: LEAVE_TYPE_LABELS.vacation,
    status,
    start_date: start,
    end_date: end,
    half_day: null,
    days_total: days,
    paid_days: days,
    unpaid_days: "0",
    note: null,
    substitute_user_id: null,
    substitute_name: null,
    forward_mail_consent: false,
    oof_internal_message: null,
    oof_external_message: null,
    decided_by_name: status === "pending" ? null : marta.name,
    decided_at: status === "pending" ? null : `${start}T09:00:00+02:00`,
    decision_note: null,
    source: "self",
    created_at: `${shiftDay(start, -14)}T10:00:00+02:00`,
    can_cancel: status === "pending",
    proof_count: 0,
    proofs: [],
    can_add_proof: status === "pending" || status === "approved",
    ...extra,
  };
}

/**
 * Wnioski Oli: urlop w tym miesiącu (wpisany do „Mojego miesiąca”), zaplanowany
 * i odrzucony. Na B2B i zleceniu (etap 2, D5) to zgłoszenia: wchodzą od razu,
 * bez akceptującego; zaplanowane ma kolizję zgłoszoną przez koordynatorkę.
 */
export function olaRequests(current: YearMonth, form: EmploymentType = "uop"): LeaveRequestRow[] {
  const month = isoMonth(current);
  const next = shiftMonth(month, 1);
  const leaveDay = harnessWorkDays(month)[3];
  const nextDays = harnessWorkDays(next);
  const previous = harnessWorkDays(shiftMonth(month, -1));
  if (form !== "uop") {
    const label = form === "b2b" ? "Przerwa w świadczeniu usług" : "Nieobecność";
    const report = {
      is_report: true,
      employment_type: form,
      leave_type_label: label,
      decided_by_name: null,
    } satisfies Partial<LeaveRequestRow>;
    return [
      request("lv-ola-2", ola, nextDays[14], nextDays[18], "5", "approved", {
        ...report,
        substitute_user_id: ewa.id,
        substitute_name: ewa.name,
        forward_mail_consent: true,
        can_cancel: true,
        conflict: {
          at: `${nextDays[0]}T09:00:00+02:00`,
          by_name: marta.name,
          note: `Odbiór projektu u klienta (${bank.name}) — czy da się przesunąć o tydzień?`,
        },
      }),
      request("lv-ola-1", ola, leaveDay, leaveDay, "1", "approved", report),
      request("lv-ola-0", ola, previous[10], previous[11], "2", "cancelled", report),
    ];
  }
  return [
    request("lv-ola-2", ola, nextDays[14], nextDays[18], "5", "approved", {
      substitute_user_id: ewa.id,
      substitute_name: ewa.name,
      forward_mail_consent: true,
      can_cancel: true,
    }),
    // Urlop okolicznościowy z aktem ślubu w załączniku (trafia do e-teczki Oli).
    request("lv-ola-3", ola, nextDays[2], nextDays[3], "2", "pending", {
      leave_type: "occasional",
      leave_type_label: LEAVE_TYPE_LABELS.occasional,
      proof_count: 1,
      proofs: [
        {
          id: 9201,
          file_name: "akt-slubu.pdf",
          mime: "application/pdf",
          size_bytes: 182_000,
          created_at: `${shiftDay(nextDays[2], -14)}T10:05:00+02:00`,
          can_remove: true,
        },
      ],
    }),
    request("lv-ola-1", ola, leaveDay, leaveDay, "1", "approved"),
    request("lv-ola-0", ola, previous[10], previous[11], "2", "rejected", {
      decision_note: "Tego dnia są dwie rozmowy u klienta — przełóż o tydzień.",
    }),
  ];
}

export function kamilRequests(current: YearMonth): LeaveRequestRow[] {
  const previous = harnessWorkDays(shiftMonth(isoMonth(current), -1));
  return [request("lv-kamil-1", kamil, previous[5], previous[6], "2", "approved")];
}

/** Zastępcy dla wniosku Kamila — proponowana Ola (ta sama rola, zna jego klientów). */
export const KAMIL_SUBSTITUTES: SubstituteCandidate[] = [
  { user_id: ola.id, name: ola.name, job_title: ola.jobTitle, department: ola.department, same_department: false, shared_role: true, suggested: true },
  { user_id: julia.id, name: julia.name, job_title: julia.jobTitle, department: julia.department, same_department: false, shared_role: true, suggested: false },
  { user_id: adam.id, name: adam.name, job_title: adam.jobTitle, department: adam.department, same_department: true, shared_role: true, suggested: false },
];

/**
 * Podgląd wniosku Kamila dla dzisiejszego dnia (okno startuje od „dziś–dziś”).
 * Dzień wolny → serwer zwraca `blocking_reason` jak `leave_policy.py`.
 */
/** Zastępcy dla zgłoszenia Oli (B2B) — bez niej samej. */
export const OLA_SUBSTITUTES: SubstituteCandidate[] = [
  { user_id: kamil.id, name: kamil.name, job_title: kamil.jobTitle, department: kamil.department, same_department: true, shared_role: true, suggested: true },
  { user_id: julia.id, name: julia.name, job_title: julia.jobTitle, department: julia.department, same_department: false, shared_role: true, suggested: false },
];

/**
 * Podgląd zgłoszenia przerwy Oli na B2B z umowną pulą (makieta m5, D5):
 * zgłoszenie, nie wniosek — koordynatorka dostaje informację.
 */
export function olaReportPreview(today: string, substituteId: number | null): LeavePreview {
  const base = kamilPreview(today, substituteId);
  return {
    ...base,
    employment_type: "b2b",
    flow: "report",
    auto_approved: true,
    years: base.years.map((split) => ({ ...split, remaining_before: "4", remaining_after: base.days_total === "1" ? "3" : "4" })),
    substitute_absent: false,
  };
}

export function kamilPreview(today: string, substituteId: number | null): LeavePreview {
  const weekday = (new Date(`${today}T12:00:00Z`).getUTCDay() + 6) % 7;
  const holiday = harnessMonthDays(today.slice(0, 7)).find((day) => day.date === today)?.kind === "holiday";
  const working = weekday < 5 && !holiday;
  const days = working ? "1" : "0";
  return {
    working_days: working ? [today] : [],
    days_total: days,
    paid_days: days,
    unpaid_days: "0",
    years: [
      {
        year: Number(today.slice(0, 4)),
        requested: days,
        paid: days,
        unpaid: "0",
        has_pool: true,
        remaining_before: "9.5",
        remaining_after: working ? "8.5" : "9.5",
      },
    ],
    blocking_reason: working ? null : "W wybranym okresie nie ma dni roboczych.",
    auto_approved: false,
    approver: marta.name,
    department_absent: [
      { user_id: adam.id, name: adam.name, start_date: today, end_date: shiftDay(today, 3) },
      { user_id: tomasz.id, name: tomasz.name, start_date: today, end_date: today },
    ],
    work: {
      total: 4,
      by_kind: [
        { kind: "client_interview", label: "Rozmowa u klienta", count: 2 },
        { kind: "prep_call", label: "Prep z kandydatem", count: 1 },
        { kind: "screening", label: "Screening", count: 1 },
      ],
      items: [
        { kind: "client_interview", label: "Rozmowa u klienta", starts_at: `${today}T10:00:00+02:00`, title: `Java Developer · ${bank.name}` },
        { kind: "prep_call", label: "Prep z kandydatem", starts_at: `${today}T11:30:00+02:00`, title: `QA Engineer · ${telecom.name}` },
        { kind: "client_interview", label: "Rozmowa u klienta", starts_at: `${today}T13:00:00+02:00`, title: `QA Engineer · ${telecom.name}` },
        { kind: "screening", label: "Screening", starts_at: `${today}T15:00:00+02:00`, title: `DevOps Engineer · ${clinic.name}` },
      ],
    },
    substitute_absent: substituteId === adam.id,
    return_on: working ? shiftDay(today, weekday === 4 ? 3 : 1) : null,
  };
}

/**
 * Saldo Oli według formy zatrudnienia (17.10.2026): B2B z umowną pulą
 * (domyślnie), UoP z limitami Kodeksu, zlecenie bez puli.
 */
export function formBalance(year: number, today: string, form: EmploymentType): LeaveBalance {
  if (form === "zlecenie") {
    return {
      ...balance(year, "0", "0"),
      employment_type: "zlecenie",
      has_pool: false,
      has_paid_pool: false,
      entitlement_days: null,
      carried_over_days: "0",
      as_of: today,
      approved_days: "0",
      used_days: "2",
      planned_days: "5",
      pending_days: "1",
      unpaid_days: "8",
      remaining_days: null,
    };
  }
  if (form === "uop") {
    return {
      ...balance(year, "11.5", "14.5"),
      employment_type: "uop",
      entitlement_days: "26",
      as_of: today,
      used_days: "12",
      planned_days: "2.5",
      pending_days: "2",
      remaining_days: "11.5",
      on_demand_used: "1",
      on_demand_limit: "4",
      childcare_used: "0",
      childcare_limit: "2",
      allowed_types: ["vacation", "on_demand", "occasional", "childcare", "sick_leave", "unpaid_leave"],
    };
  }
  return {
    ...balance(year, "11.5", "14.5"),
    entitlement_days: "24",
    as_of: today,
    used_days: "12",
    planned_days: "2.5",
    pending_days: "0",
    remaining_days: "11.5",
  };
}

// ── Mój miesiąc ─────────────────────────────────────────────────────────────

const DESCRIPTIONS: { project: string | null; text: string }[] = [
  { project: bank.name, text: `Screening: Java Developer, ${bank.name}` },
  { project: null, text: "Weryfikacje kandydatów, 2 rekomendacje do klienta" },
  { project: telecom.name, text: `Rozmowa u klienta: ${telecom.name}, QA Engineer` },
  { project: clinic.name, text: `Sourcing: DevOps Engineer, ${clinic.name}` },
];

/**
 * Miesiąc Oli: dni do wczoraj wpisane (urlop z wniosku i jeden dzień
 * z nadgodziną), dziś bez wpisu, jutro zaplanowane zdalnie, reszta pusta.
 */
export function olaMonth(
  period: YearMonth,
  today: string,
  approved: boolean,
  form: EmploymentType = "b2b",
): MonthView {
  return { ...personMonth(ola, period, today, approved ? "approved" : "draft"), employment_type: form };
}

/** Archiwum timesheetów Oli: bieżący szkic, poprzednie zaakceptowane (12 miesięcy). */
export function olaHistory(current: YearMonth): TimesheetHistoryItem[] {
  return Array.from({ length: 12 }, (_, index) => {
    const index0 = current.year * 12 + (current.month - 1) - index;
    const year = Math.floor(index0 / 12);
    const month = (index0 % 12) + 1;
    return {
      id: 9000 + index,
      year,
      month,
      status: index === 0 ? "draft" : "approved",
      approved_at: index === 0 ? null : `${year}-${String(month).padStart(2, "0")}-28T12:00:00+01:00`,
      hours: index === 0 ? 121 : 160 + (index % 3) * 8,
    } satisfies TimesheetHistoryItem;
  });
}

export type HarnessTimesheetMode = "draft" | "submitted" | "approved" | "missing";

/** Miesiąc osoby w danym stanie timesheetu (`missing` = bez timesheetu i wpisów). */
export function personMonth(
  person: HarnessPerson,
  period: YearMonth,
  today: string,
  mode: HarnessTimesheetMode,
): MonthView {
  const approved = mode === "approved" || mode === "submitted";
  const month = isoMonth(period);
  const workDays = harnessWorkDays(month);
  const leaveDay = workDays[3];
  const overtimeDay = workDays[4];
  const plannedRemote = workDays.find((day) => day > today) ?? null;
  let entryId = period.month * 1000;
  const days: MonthDay[] = harnessMonthDays(month).map((day) => {
    const working = day.kind === "work";
    const past = mode !== "missing" && (approved || day.date < today);
    const base: MonthDay = {
      date: day.date,
      weekday: day.weekday + 1,
      is_weekend: day.kind === "weekend",
      holiday: day.kind === "holiday" ? day.name : null,
      day_off: null,
      working_day: working,
      location: null,
      location_source: null,
      attendance_status: null,
      attendance_note: null,
      leave: null,
      entries: [],
      hours: 0,
      capacity: working ? 8 : 0,
      overtime_hours: 0,
    };
    if (!working) return base;
    if (day.date === leaveDay) {
      const entry: TimesheetEntry = {
        id: ++entryId,
        work_date: day.date,
        hours: 8,
        project: null,
        description: "Urlop wypoczynkowy",
        source: "leave_paid",
        is_overtime: false,
        overtime_reason: null,
      };
      return {
        ...base,
        leave: { status: "approved", fraction: 1, full: true, paid_work: true, paid_hours: 8, label: LEAVE_TYPE_LABELS.vacation },
        entries: [entry],
        hours: 8,
        capacity: null,
      };
    }
    const index = workDays.indexOf(day.date);
    const remote = index % 5 === 2;
    if (!past) {
      return day.date === plannedRemote
        ? { ...base, location: "remote", location_source: "exception", attendance_status: "active", attendance_note: "zaplanowane zdalnie" }
        : { ...base, location: day.date === today ? "onsite" : null, location_source: day.date === today ? "default" : null };
    }
    const pick = DESCRIPTIONS[index % DESCRIPTIONS.length];
    const overtime = mode !== "approved" && day.date === overtimeDay;
    const entries: TimesheetEntry[] = [
      {
        id: ++entryId,
        work_date: day.date,
        hours: overtime ? 9 : 8,
        project: pick.project,
        description: overtime ? "Screening + spotkanie z DL po godzinach" : pick.text,
        source: "manual",
        is_overtime: overtime,
        overtime_reason: overtime ? "Spotkanie z Delivery Leadem o kandydatach po 17:00" : null,
      },
    ];
    const hours = overtime ? 9 : 8;
    return {
      ...base,
      location: remote ? "remote" : "onsite",
      location_source: remote ? "exception" : "default",
      attendance_status: "active",
      entries,
      hours,
      capacity: 0,
      overtime_hours: overtime ? 1 : 0,
    };
  });
  const work = days.flatMap((day) => day.entries).filter((entry) => entry.source === "manual");
  const workingDays = workDays.length;
  const next = shiftMonth(month, 1);
  return {
    user_id: person.id,
    name: person.name,
    year: period.year,
    month: period.month,
    deadline: `${next}-05`,
    employment_type: "b2b",
    default_location: "onsite",
    can_log_overtime: true,
    approver_name: marta.name,
    timesheet:
      mode === "missing"
        ? null
        : approved
      ? {
          id: person.id * 100 + period.month,
          status: mode === "submitted" ? "submitted" : "approved",
          submitted_at: `${next}-02T09:00:00+01:00`,
          return_note: null,
          returned_at: null,
          approved_at: mode === "submitted" ? null : `${next}-03T12:00:00+01:00`,
          approved_by_name: mode === "submitted" ? null : marta.name,
          payroll_locked: false,
          pdf_hash: mode === "submitted" ? null : "test-hash-0001",
        }
      : {
          id: person.id * 100 + period.month,
          status: "draft",
          submitted_at: null,
          return_note: null,
          returned_at: null,
          approved_at: null,
          approved_by_name: null,
          payroll_locked: false,
          pdf_hash: null,
        },
    days,
    totals: {
      work_hours: work.reduce((sum, entry) => sum + entry.hours, 0),
      leave_paid_hours: days.filter((day) => day.leave?.paid_work).length * 8,
      overtime_hours: days.reduce((sum, day) => sum + day.overtime_hours, 0),
      leave_days: days.filter((day) => day.leave).length,
      working_days: workingDays,
      norm_hours: workingDays * 8,
      days_missing: days.filter((day) => day.working_day && day.entries.length === 0 && !day.leave).length,
    },
  };
}

export const TEMPLATES: { items: TimesheetTemplate[]; role_default: { label: string; description: string; project: string | null } | null } = {
  items: [
    { id: 1, name: "Rekrutacja", description: "Sourcing i rozmowy z kandydatami", project: null, sort_order: 1 },
    { id: 2, name: "Rozmowy u klienta", description: "Rozmowy u klienta z kandydatami", project: null, sort_order: 2 },
  ],
  role_default: { label: "Rekruter", description: "Sourcing i rozmowy z kandydatami", project: null },
};

/** Podpowiedź opisu dnia z pracy w NEXUSIE (tylko po kliknięciu „Wstaw opis”). */
export function dayHint(day: string, today: string): DayHint {
  const busy = day === today;
  return {
    day,
    counts: {
      calls: busy ? 7 : 0,
      stage_moves: busy ? 3 : 0,
      verifications: busy ? 2 : 0,
      cv_sent: 0,
      client_interviews: busy ? 1 : 0,
      notes: busy ? 4 : 0,
    },
    jobs: busy ? [`DevOps Engineer · ${clinic.name}`] : [],
    client_interviews: busy ? [{ time: "14:00", job: `DevOps Engineer · ${clinic.name}` }] : [],
    text: busy
      ? `7 rozmów z kandydatami, 2 weryfikacje, rozmowa u klienta 14:00 (${clinic.name})`
      : null,
  };
}

// ── Premie ──────────────────────────────────────────────────────────────────

function rate(id: number, value: string, from: string, to: string | null): RateRow {
  return { id, user_id: ola.id, hourly_rate: value, currency: "PLN", effective_from: from, effective_to: to, reason: null, set_by: null };
}

function bonus(id: number, over: Partial<BonusRow> & Pick<BonusRow, "amount" | "category" | "category_label" | "period_year" | "period_month">): BonusRow {
  return {
    id,
    recipient_user_id: ola.id,
    recipient_name: ola.name,
    proposed_by: null,
    proposed_by_name: null,
    currency: "PLN",
    status: "assigned",
    source: "contract_placement",
    contract_id: null,
    eligible_on: null,
    description: null,
    assigned_by: null,
    assigned_at: null,
    cancelled_at: null,
    cancel_reason: null,
    edited: false,
    ...over,
  };
}

/** Premia „w drodze” z umowy podpisanej przed startem (szacunek, bez wiersza w bazie). */
function forecast(today: string, over: Partial<BonusForecast>): BonusForecast {
  return {
    key: "contract:9301:recruiter",
    contract_id: 9301,
    role: "recruiter",
    category: "recruiter",
    category_label: "Rekruter",
    description: `Premia rekrutera — placement: Jan Konsultantowy (${bank.name})`,
    amount: "2000.00",
    currency: "PLN",
    amount_missing_reason: null,
    start_date: shiftDay(today, 11),
    started: false,
    eligible_on: shiftDay(today, 41),
    business_days_elapsed: 0,
    business_days_required: 21,
    ...over,
  };
}

export function olaPayroll(current: YearMonth, today: string = `${isoMonth(current)}-22`): MyPayroll {
  const previous = shiftMonth(isoMonth(current), -1);
  const [prevYear, prevMonth] = previous.split("-").map(Number);
  return {
    forecast: [forecast(today, {})],
    business_days_required: 21,
    ...olaPayrollBase(current, previous, prevYear, prevMonth),
  };
}

function olaPayrollBase(
  current: YearMonth,
  previous: string,
  prevYear: number,
  prevMonth: number,
): Pick<MyPayroll, "current_rate" | "rates" | "bonuses"> {
  return {
    current_rate: rate(2, "120.00", `${current.year}-07-01`, null),
    rates: [rate(2, "120.00", `${current.year}-07-01`, null), rate(1, "110.00", "2025-03-03", `${current.year}-06-30`)],
    bonuses: [
      bonus(11, {
        amount: "1500.00",
        category: "recruiter",
        category_label: "Premia rekrutera",
        period_year: prevYear,
        period_month: prevMonth,
        description: `Premia rekrutera — placement: Michał Konsultantowy (${bank.name})`,
        assigned_at: `${previous}-28T10:00:00+02:00`,
        assigned_by_name: marta.name,
        period_closed: true,
      }),
      bonus(12, {
        amount: "3000.00",
        category: "league",
        category_label: "Liga Mistrzów",
        period_year: prevYear,
        period_month: prevMonth,
        source: "league",
        description: "Liga Mistrzów — 2. miejsce w kwartale",
        assigned_at: `${previous}-28T10:00:00+02:00`,
        assigned_by_name: ewa.name,
        period_closed: false,
      }),
      bonus(13, {
        amount: "1000.00",
        category: "recruiter",
        category_label: "Premia rekrutera",
        period_year: current.year,
        period_month: current.month,
        status: "proposed",
        description: `Premia rekrutera — placement: Bartosz Testowy (${telecom.name})`,
        eligible: false,
        eligible_on: `${isoMonth(current)}-28`,
        business_days_elapsed: 14,
        business_days_required: 21,
      }),
      bonus(14, {
        amount: "1500.00",
        category: "recruiter",
        category_label: "Premia rekrutera",
        period_year: prevYear,
        period_month: prevMonth,
        status: "cancelled",
        description: `Premia rekrutera — placement: Adam Próbny (${clinic.name})`,
        cancel_reason: "contract_ended",
        cancelled_at: `${previous}-20T10:00:00+02:00`,
      }),
    ],
  };
}

/** „Moje rozliczenie”: poprzedni miesiąc zamknięty, bieżący jako szacunek z „Mojego miesiąca”. */
export function olaSettlement(current: YearMonth): MySettlement {
  const previous = shiftMonth(isoMonth(current), -1);
  const [prevYear, prevMonth] = previous.split("-").map(Number);
  const months: MySettlement["months"] = [
    {
      year: current.year,
      month: current.month,
      label: `${isoMonth(current)}`,
      final: false,
      hours: "121.00",
      hours_source: "entered",
      timesheet_status: "draft",
      rate_missing: false,
      lines: [
        { currency: "PLN", hourly_rate: "120.00", hours_amount: "14520.00", bonus_total: "0.00", total: "14520.00" },
      ],
    },
  ];
  if (prevYear === current.year) {
    months.push({
      year: prevYear,
      month: prevMonth,
      label: previous,
      final: true,
      hours: "168.00",
      hours_source: "frozen",
      timesheet_status: "approved",
      rate_missing: false,
      lines: [
        { currency: "PLN", hourly_rate: "120.00", hours_amount: "20160.00", bonus_total: "1500.00", total: "21660.00" },
      ],
    });
  }
  return {
    year: current.year,
    months: months.map((month) => ({ ...month, label: monthYearPl(month) })),
    bonuses_paid: prevYear === current.year ? { PLN: "1500.00" } : {},
  };
}


// ── Zgody i wydatki (`?tab=consents`, 22.10.2026) ─────────────────────────────

function consent(
  partial: Partial<ApprovalRequestRow> & Pick<ApprovalRequestRow, "id" | "kind" | "title">,
): ApprovalRequestRow {
  return {
    kind_label: "Inny wydatek",
    status: "pending_final",
    status_label: "Czeka na zatwierdzającego",
    purpose: "",
    amount: "100.00",
    decided_amount: null,
    currency: "PLN",
    amount_basis: "gross",
    recurrence: "once",
    amount_text: "100 zł brutto",
    payer: "company_invoice",
    link_url: null,
    needed_by: null,
    starts_on: null,
    ends_on: null,
    beneficiary_user_id: null,
    beneficiary_name: null,
    payout_year: null,
    payout_month: null,
    requester_user_id: ola.id,
    requester_name: ola.name,
    supervisor_user_id: marta.id,
    supervisor_name: marta.name,
    needs_final: true,
    final_approver_names: ["Aniela Administrująca"],
    endorsed_by_name: null,
    endorsed_at: null,
    endorse_note: null,
    decided_by_name: null,
    decided_at: null,
    decision_note: null,
    decision_channel: null,
    bonus_id: null,
    submitted_at: `${shiftDay(warsawToday(), -2)}T08:12:00Z`,
    can_decide: false,
    decides_as: null,
    can_edit: false,
    can_withdraw: false,
    context: null,
    ...partial,
  };
}

/** Moje zgody Oli: pytanie od zatwierdzającej (do zrobienia), szkolenie w toku, zamknięta subskrypcja. */
export function olaConsents(): ApprovalRequestRow[] {
  return [
    consent({
      id: 9101,
      kind: "trip",
      kind_label: "Koszty podróży",
      title: "Spotkanie u klienta w Gdańsku",
      purpose: "Warsztat wymagań z zespołem klienta, dwa dni na miejscu.",
      amount: "1200.00",
      amount_text: "1 200 zł brutto",
      status: "returned",
      status_label: "Pytanie do Ciebie",
      decided_by_name: "Aniela Administrująca",
      decision_note: "Czy nocleg jest w tej kwocie?",
      can_edit: true,
      can_withdraw: true,
    }),
    consent({
      id: 9102,
      kind: "training",
      kind_label: "Szkolenie",
      title: "Kurs rekrutacji technicznej",
      purpose: "Kurs online, certyfikat do profilu.",
      amount: "890.00",
      amount_text: "890 zł brutto",
      can_withdraw: true,
    }),
    consent({
      id: 9103,
      kind: "subscription",
      kind_label: "Subskrypcja",
      title: "Narzędzie do notatek",
      purpose: "Notatki z rozmów z kandydatami.",
      amount: "49.00",
      amount_text: "49 zł brutto miesięcznie",
      recurrence: "monthly",
      status: "approved",
      status_label: "Zatwierdzona",
      decided_by_name: "Marta Fikcyjna",
      decided_at: `${shiftDay(warsawToday(), -10)}T10:00:00Z`,
    }),
  ];
}
