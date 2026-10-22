"use client";

/**
 * Harness „Ludzie → Kalendarz” (makieta 3 raportu „Ludzie w NEXUSIE”).
 *
 * Prawdziwe `PeopleSectionNav` + `TeamCalendar` na zasianym cache, ZERO zapytań
 * (`hr-harness.tsx`). Miesiąc to bieżący miesiąc przeglądarki — ekran liczy
 * „dziś” sam, więc dane i klucze budujemy względem niego (`hr-fixtures.ts`).
 *
 * Stany (`?as=`):
 * - `team` (domyślnie) — rekruterka bez podwładnych: widzi „nieobecny”, bez
 *   rodzaju (D6), bez chipa „Mój zespół”, domyślnie „Wszyscy”;
 * - `manager` — przełożona: domyślnie chip „Mój zespół” i rodzaj nieobecności
 *   swoich ludzi (osoba, przełożony i Kadry).
 * „Wszyscy”, „Mój zespół” i sąsiednie miesiące (±2, także widok „2 tygodnie”
 * na przełomie miesięcy) są zasiane — klik nie wysyła zapytania; działy
 * filtruje ekran na danych „Wszyscy”. Filtry ekranu dopisują się do adresu
 * obok `?as=`.
 * Układ z makiety 19.10.2026: ciągłe paski, wiersz „Nieobecnych”, panel
 * „W tym tygodniu nie ma”, „Znajdź osobę”.
 */

import { PageHeader } from "@/components/ds/PageHeader";
import { TeamCalendar } from "@/components/hr/leave/TeamCalendar";
import { LEAVE_TYPE_LABELS } from "@/components/hr/leave/leave-format";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";
import { hrKeys, type HrConfig } from "@/lib/api/hr";
import {
  leaveKeys,
  type CalendarAbsence,
  type CalendarPresenceKind,
  type LeaveType,
  type TeamCalendar as TeamCalendarData,
  type TeamCalendarPerson,
} from "@/lib/api/hr-leave";
import { warsawToday } from "@/lib/warsaw-date";
import { shiftMonth } from "@/lib/date-pl";

import {
  HR_CAST,
  hrConfig,
  harnessMonthDays,
  nthWorkDay,
  type HarnessPerson,
} from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";

const AS = ["team", "manager"] as const;
type As = (typeof AS)[number];

const STATES = [
  { key: "team", label: "Rekruterka (rodzaj ukryty)" },
  { key: "manager", label: "Przełożona (Mój zespół)" },
] as const;

interface Plan {
  person: HarnessPerson;
  /** Przedziały w dniach roboczych miesiąca (od 1). */
  ranges: { from: number; to: number; type: LeaveType; pending?: boolean; half?: boolean; substitute?: HarnessPerson }[];
}

const { ola, kamil, ewa, adam, marta, tomasz, julia, zofia } = HR_CAST;

const PLANS: Plan[] = [
  { person: kamil, ranges: [{ from: 3, to: 6, type: "vacation", substitute: ola }, { from: 19, to: 19, type: "on_demand" }] },
  { person: ola, ranges: [{ from: 15, to: 17, type: "vacation", pending: true, substitute: ewa }] },
  { person: ewa, ranges: [{ from: 1, to: 3, type: "sick_leave", substitute: julia }] },
  { person: tomasz, ranges: [{ from: 5, to: 6, type: "vacation", substitute: adam }] },
  { person: julia, ranges: [{ from: 11, to: 15, type: "vacation", substitute: tomasz }] },
  { person: adam, ranges: [{ from: 9, to: 9, type: "training", half: true }] },
  { person: zofia, ranges: [{ from: 2, to: 3, type: "sick_leave" }] },
  { person: marta, ranges: [] },
];

/** Podwładni przełożonej — tylko oni mają w jej widoku rodzaj nieobecności. */
const REPORTS = new Set<number>([ola.id, ewa.id, tomasz.id, julia.id]);

/** Praca zdalna i delegacja (n-ty dzień roboczy miesiąca) — fikcyjne, do podglądu znaczników „Z” i „D”. */
const PRESENCE: Record<number, [number, CalendarPresenceKind][]> = {
  [ola.id]: [[2, "remote"], [3, "remote"], [9, "remote"]],
  [tomasz.id]: [[1, "remote"], [12, "business_trip"], [13, "business_trip"]],
  [marta.id]: [[6, "remote"], [7, "remote"]],
};

function calendar(month: string, viewer: HarnessPerson, as: As, filter: (p: HarnessPerson) => boolean): TeamCalendarData {
  const today = warsawToday();
  const people: TeamCalendarPerson[] = PLANS.filter((plan) => filter(plan.person)).map(({ person, ranges }) => {
    const typeVisible = person.id === viewer.id || (as === "manager" && REPORTS.has(person.id));
    const absences: CalendarAbsence[] = ranges.map((range, index) => ({
      id: typeVisible ? `${person.id}-${month}-${index}` : null,
      start_date: nthWorkDay(month, range.from),
      end_date: nthWorkDay(month, range.to),
      half_day: range.half ? "morning" : null,
      status: range.pending ? "pending" : "approved",
      label: typeVisible ? LEAVE_TYPE_LABELS[range.type] : "Nieobecność",
      leave_type: typeVisible ? range.type : null,
      substitute_user_id: range.substitute?.id ?? null,
      substitute_name: range.substitute?.name ?? null,
    }));
    return {
      user_id: person.id,
      name: person.name,
      department: person.department,
      job_title: person.jobTitle,
      is_me: person.id === viewer.id,
      type_visible: typeVisible,
      absences,
      presence: (PRESENCE[person.id] ?? []).map(([day, kind]) => ({ date: nthWorkDay(month, day), kind })),
    };
  });
  return {
    month,
    today,
    days: harnessMonthDays(month),
    departments: [...new Set(PLANS.map((plan) => plan.person.department))].sort(),
    presence_shown: true,
    people,
  };
}

function prepare(params: URLSearchParams) {
  const as = pickState(params.get("as"), AS, "team");
  const viewer = as === "manager" ? marta : ola;
  const config: HrConfig = hrConfig(
    as === "manager" ? { is_manager: true, direct_reports: REPORTS.size } : {},
  );
  const client = harnessQueryClient();
  client.setQueryData(hrKeys.config, config);
  client.setQueryData(hrKeys.counts, { approvals: as === "manager" ? 4 : null, cases: null });
  const current = warsawToday().slice(0, 7);
  // Widok 2 tygodni na przełomie miesięcy czyta dwa miesiące — zasiane ±2.
  for (const month of [-2, -1, 0, 1, 2].map((delta) => shiftMonth(current, delta))) {
    client.setQueryData(leaveKeys.calendar(month, null, false), calendar(month, viewer, as, () => true));
    client.setQueryData(
      leaveKeys.calendar(month, null, true),
      calendar(month, viewer, as, (p) => REPORTS.has(p.id) || p.id === viewer.id),
    );
  }
  return { user: viewer, client, value: { as, config } };
}

export default function HrCalendarPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { as, config } = ready.value;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Ludzie → Kalendarz"
      note="Dane fikcyjne, bez zapytań. Rodzaj nieobecności widzą tylko osoba, jej przełożony i Kadry (D6)."
      states={STATES}
      current={as}
      param="as"
    >
      <div className="space-y-4">
        <PageHeader
          title="Kalendarz"
          description="Nieobecności w zespole. Rodzaj widzą tylko osoba, jej koordynator i Kadry."
          density="compact"
        />
        <PeopleSectionNav config={config} active="calendar" />
        <TeamCalendar config={config} />
      </div>
    </HrHarnessShell>
  );
}
