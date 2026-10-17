/**
 * Dane harnessu `/preview/hr-payroll` (makieta 7 „Płace i premie”).
 *
 * Scena: zamknięcie POPRZEDNIEGO miesiąca względem dziś (makieta: wrzesień
 * otwarty na początku października). Daty i okresy liczone od zegara
 * przeglądarki, jak w ekranie. Kwoty zmyślone, policzone jak serwer
 * (`payroll_report.py`): do kwot wchodzą tylko zaakceptowane godziny,
 * premie osoby to suma premii przyznanych w miesiącu.
 */

import { CATEGORY_LABELS } from "@/components/hr/payroll/payroll-format";
import type {
  BonusCategory,
  BonusRow,
  BonusSource,
  PayrollMonthDetail,
  PayrollMonthSummary,
  PayrollPerson,
  TimesheetStatus,
} from "@/lib/api/hr-payroll";
import type { EmploymentType } from "@/lib/api/hr";
import { warsawToday } from "@/lib/warsaw-date";
import { shiftMonth, monthYearPl } from "@/lib/date-pl";

import { HR_CAST, HR_CLIENTS, HR_CONSULTANTS, harnessWorkDays, nthWorkDay, type HarnessPerson } from "../hr-fixtures";
import { addWorkDays } from "../hr-person/fixtures";

const { kamil, ola, ewa, adam, tomasz, julia, zofia, marta, piotr } = HR_CAST;

/** Podwładni Marty (przełożona z widoku D2). */
export const MARTA_REPORTS = new Set<number>([ola.id, ewa.id, tomasz.id, julia.id]);

export interface PayrollScene {
  today: string;
  /** Bieżący miesiąc `RRRR-MM`. */
  current: string;
  /** Miesiąc do zamknięcia (poprzedni) `RRRR-MM`. */
  closing: string;
  year: number;
  month: number;
}

export function payrollScene(): PayrollScene {
  const today = warsawToday();
  const current = today.slice(0, 7);
  const closing = shiftMonth(current, -1);
  const [year, month] = closing.split("-").map(Number);
  return { today, current, closing, year, month };
}

function period(day: string): { period_year: number; period_month: number } {
  const [year, month] = day.split("-").map(Number);
  return { period_year: year, period_month: month };
}

interface BonusSpec {
  id: number;
  to: HarnessPerson;
  amount: string;
  category: BonusCategory;
  source: BonusSource;
  description: string;
  period: { period_year: number; period_month: number };
  status?: BonusRow["status"];
  eligibleOn?: string | null;
  today: string;
  contractId?: number | null;
  assignedAt?: string | null;
  progress?: number | null;
}

function bonus(spec: BonusSpec): BonusRow {
  const status = spec.status ?? "proposed";
  return {
    id: spec.id,
    recipient_user_id: spec.to.id,
    recipient_name: spec.to.name,
    proposed_by: null,
    proposed_by_name: null,
    amount: spec.amount,
    currency: "PLN",
    category: spec.category,
    category_label: CATEGORY_LABELS[spec.category],
    ...spec.period,
    status,
    source: spec.source,
    contract_id: spec.contractId ?? null,
    eligible_on: spec.eligibleOn ?? null,
    ...(spec.eligibleOn ? { eligible: spec.eligibleOn <= spec.today } : {}),
    description: spec.description,
    assigned_by: status === "assigned" ? piotr.id : null,
    assigned_at: status === "assigned" ? (spec.assignedAt ?? null) : null,
    cancelled_at: null,
    cancel_reason: null,
    edited: false,
    ...(spec.progress != null
      ? { business_days_elapsed: spec.progress, business_days_required: 21 }
      : {}),
  };
}

const MICHAL = `${HR_CONSULTANTS.michal.name} (${HR_CLIENTS.bank.name})`;
const KAROLINA = `${HR_CONSULTANTS.karolina.name} (${HR_CLIENTS.telecom.name})`;
const BARTOSZ = `${HR_CONSULTANTS.bartosz.name} (${HR_CLIENTS.bank.name})`;

/**
 * Premie miesiąca do zamknięcia (bez filtra widoczności): dwie przyznane
 * z placementu Michała, dwie propozycje z placementu Karoliny po terminie
 * i trzy propozycje z Ligi (1.–3. miejsce).
 */
export function closingBonuses(scene: PayrollScene): BonusRow[] {
  const { closing, today } = scene;
  const target = period(`${closing}-01`);
  const lastDay = harnessWorkDays(closing).at(-1) ?? `${closing}-28`;
  const assignedAt = `${nthWorkDay(scene.current, 2)}T08:30:00Z`;
  const karolinaDue = nthWorkDay(closing, 14);
  const quarter = `Q${Math.ceil(scene.month / 3)} ${scene.year}`;
  const common = { today, period: target };
  return [
    bonus({ ...common, id: 701, to: kamil, amount: "772.80", category: "delivery_lead", source: "contract_placement", description: `Premia DL — placement: ${MICHAL}`, status: "assigned", eligibleOn: lastDay, contractId: 8101, assignedAt }),
    bonus({ ...common, id: 702, to: ola, amount: "1500.00", category: "recruiter", source: "contract_placement", description: `Premia rekrutera — placement: ${MICHAL}`, status: "assigned", eligibleOn: lastDay, contractId: 8101, assignedAt }),
    bonus({ ...common, id: 703, to: adam, amount: "529.20", category: "delivery_lead", source: "contract_placement", description: `Premia DL — placement: ${KAROLINA}`, eligibleOn: karolinaDue, contractId: 8102 }),
    bonus({ ...common, id: 704, to: tomasz, amount: "1000.00", category: "recruiter", source: "contract_placement", description: `Premia rekrutera — placement: ${KAROLINA}`, eligibleOn: karolinaDue, contractId: 8102 }),
    bonus({ ...common, id: 705, to: julia, amount: "5000.00", category: "league", source: "league", description: `Liga Mistrzów rekruterów — ${quarter}, 1. miejsce` }),
    bonus({ ...common, id: 706, to: ola, amount: "3000.00", category: "league", source: "league", description: `Liga Mistrzów rekruterów — ${quarter}, 2. miejsce` }),
    bonus({ ...common, id: 707, to: ewa, amount: "2000.00", category: "league", source: "league", description: `Liga Mistrzów rekruterów — ${quarter}, 3. miejsce` }),
  ];
}

/** Placement Bartosza: 10 z 21 dni roboczych, termin w przyszłości. */
export function inProgressBonuses(scene: PayrollScene): BonusRow[] {
  const due = addWorkDays(scene.today, 11);
  const common = { today: scene.today, period: period(due), eligibleOn: due, contractId: 8103, progress: 10 };
  return [
    bonus({ ...common, id: 708, to: kamil, amount: "873.60", category: "delivery_lead", source: "contract_placement", description: `Premia DL — placement: ${BARTOSZ}` }),
    bonus({ ...common, id: 709, to: ewa, amount: "2000.00", category: "recruiter", source: "contract_placement", description: `Premia rekrutera — placement: ${BARTOSZ}` }),
  ];
}

interface PersonSpec {
  person: HarnessPerson;
  type: EmploymentType;
  status: TimesheetStatus | null;
  /** Godziny w timesheecie (do kwot wchodzą tylko zaakceptowane). */
  hours: number;
  rate: number;
}

const PEOPLE: PersonSpec[] = [
  { person: kamil, type: "b2b", status: "approved", hours: 176, rate: 130 },
  { person: ola, type: "b2b", status: "approved", hours: 176, rate: 120 },
  { person: ewa, type: "uop", status: "approved", hours: 168, rate: 95 },
  { person: tomasz, type: "b2b", status: "submitted", hours: 176, rate: 110 },
  { person: zofia, type: "zlecenie", status: "approved", hours: 96, rate: 60 },
  { person: julia, type: "b2b", status: null, hours: 0, rate: 115 },
];

function money(value: number): string {
  return value.toFixed(2);
}

function assignedSum(bonuses: BonusRow[], userId: number): number {
  return bonuses
    .filter((row) => row.status === "assigned" && row.recipient_user_id === userId)
    .reduce((sum, row) => sum + Number(row.amount), 0);
}

function byName(a: { name: string }, b: { name: string }): number {
  return a.name.localeCompare(b.name, "pl");
}

/** Wiersze osób: Płace z kwotami, przełożony — godziny i premie (D2). */
export function payrollPeople(bonuses: BonusRow[], scope: "payroll" | "team"): PayrollPerson[] {
  return PEOPLE.filter(({ person }) => scope === "payroll" || MARTA_REPORTS.has(person.id))
    .map(({ person, type, status, hours, rate }) => {
      const approvedHours = status === "approved" ? hours : 0;
      const bonusTotal = assignedSum(bonuses, person.id);
      const hoursAmount = approvedHours * rate;
      const base = {
        user_id: person.id,
        name: person.name,
        employment_type: type,
        timesheet_required: true,
        timesheet_status: status,
        hours: money(approvedHours),
        overtime_hours: "0.00",
        paid_leave_days: "0.0",
        other_leave_days: "0.0",
      };
      if (scope === "team") {
        return {
          ...base,
          bonuses: bonusTotal > 0 ? [{ currency: "PLN" as const, bonus_total: money(bonusTotal) }] : [],
        };
      }
      return {
        ...base,
        rate_missing: false,
        lines: [
          {
            currency: "PLN" as const,
            hourly_rate: money(rate),
            hours_amount: money(hoursAmount),
            bonus_total: money(bonusTotal),
            total: money(hoursAmount + bonusTotal),
          },
        ],
      };
    })
    .sort(byName);
}

/** `GET /api/hr/payroll/months/{rok}/{miesiąc}` dla Płac albo przełożonej. */
export function closingDetail(scene: PayrollScene, scope: "payroll" | "team"): PayrollMonthDetail {
  const all = closingBonuses(scene);
  const visible = (row: BonusRow) =>
    scope === "payroll" || row.recipient_user_id === marta.id || MARTA_REPORTS.has(row.recipient_user_id);
  const bonuses = all.filter(visible);
  const people = payrollPeople(all, scope);
  const stat = (status: TimesheetStatus | null) => people.filter((p) => p.timesheet_status === status).length;
  const detail: PayrollMonthDetail = {
    year: scene.year,
    month: scene.month,
    label: monthYearPl(scene),
    status: "open",
    frozen: false,
    scope,
    closed_at: null,
    reopened_at: null,
    reopen_reason: null,
    can_close: scope === "payroll",
    can_reopen: false,
    stats: {
      people: people.length,
      timesheets_approved: stat("approved"),
      timesheets_submitted: stat("submitted"),
      timesheets_missing: stat(null),
      proposals: bonuses.filter((row) => row.status === "proposed").length,
    },
    people,
    bonuses,
    in_progress: inProgressBonuses(scene).filter(visible),
  };
  if (scope === "team") return detail;
  const total = people.reduce((sum, p) => sum + Number(p.lines?.[0]?.total ?? 0), 0);
  const unapproved = people.filter((p) => p.timesheet_status !== "approved");
  return {
    ...detail,
    totals: { PLN: money(total) },
    warnings: [
      {
        code: "unapproved_timesheets",
        message: `${unapproved.length} os. bez zatwierdzonego timesheetu — ich godziny nie wejdą do płac tego miesiąca.`,
        count: unapproved.length,
        people: unapproved.map((p) => ({ user_id: p.user_id, name: p.name, timesheet_status: p.timesheet_status })),
      },
    ],
  };
}

/** `GET /api/hr/payroll/months` — 13 miesięcy od bieżącego wstecz. */
export function monthsList(scene: PayrollScene): PayrollMonthSummary[] {
  const closing = closingDetail(scene, "payroll");
  const inProgress = inProgressBonuses(scene);
  return Array.from({ length: 13 }, (_, index): PayrollMonthSummary => {
    const ym = shiftMonth(scene.current, -index);
    const [year, month] = ym.split("-").map(Number);
    const pending = inProgress.filter((row) => row.period_year === year && row.period_month === month).length;
    const base = { year, month, label: monthYearPl({ year, month }), people: PEOPLE.length };
    if (index === 0) {
      return { ...base, status: "open" as const, totals: {}, pending_proposals: pending, can_close: false };
    }
    if (index === 1) {
      return {
        ...base,
        status: "open" as const,
        totals: closing.totals ?? {},
        pending_proposals: closing.stats.proposals + pending,
        can_close: true,
      };
    }
    return {
      ...base,
      status: "closed" as const,
      totals: { PLN: money(64000 + ((index * 1379) % 5000) + 0.4 * index) },
      pending_proposals: 0,
      can_close: false,
    };
  });
}
