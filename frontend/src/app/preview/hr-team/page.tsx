"use client";

/**
 * Harness „Ludzie → Mój zespół” (etap 2, makieta „Mój zespół”, D6).
 *
 * Prawdziwe `PeopleSectionNav` + `TeamScreen` na zasianym cache, ZERO zapytań
 * (`hr-harness.tsx`). Zespół Marty: większość na B2B albo zleceniu (bez puli
 * albo, jak Ola, z wierszem puli 0 — kolumna „Nieobecności” pokazuje
 * zaplanowane dni), Julia na UoP z pulą.
 *
 * Układ z makiety 19.10.2026 (wiersze decyzji 22.10.2026): pasek „Dziś”,
 * zwarte wiersze „Do Twojej decyzji” (Akceptuj / Odrzuć na miejscu — w podglądzie zapis to błąd sieci, testy
 * klikają tylko „Odrzuć”, które otwiera okno), mini-tydzień pn–pt i pasek
 * godzin miesiąca.
 *
 * Stany (`?as=`):
 * - `manager` (domyślnie) — Marta o swoich ludziach: Ewa na przerwie (rodzaj
 *   widzi przełożona, D6), Ola ją zastępuje, Tomasz dziś w delegacji, Adam
 *   w czwartek zdalnie, premie z kwotą bez stawek, wniosek Julii i timesheet
 *   Tomasza do decyzji, propozycja premii Oli do wiadomości;
 * - `hr` — Paulina (Kadry bez Płac) ogląda zespół Marty z wyboru przełożonego:
 *   bez kolumny premii.
 */

import { PageHeader } from "@/components/ds/PageHeader";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";
import { TeamScreen } from "@/components/hr/team/TeamScreen";
import { hrKeys, type HrConfig } from "@/lib/api/hr";
import { addDays, mondayOf } from "@/components/hr/leave/calendar-bars";
import {
  teamKeys,
  type MyTeam,
  type TeamBonusItem,
  type TeamPerson,
  type TeamWeekDay,
  type TeamWeekState,
} from "@/lib/api/hr-team";
import { warsawToday } from "@/lib/warsaw-date";

import {
  HR_CAST,
  harnessWorkDays,
  hrConfig,
  shiftDay,
  type HarnessPerson,
} from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";

const AS = ["manager", "hr"] as const;

const STATES = [
  { key: "manager", label: "Przełożona (Marta)" },
  { key: "hr", label: "Kadry (zespół Marty)" },
] as const;

const { marta, ola, ewa, tomasz, julia, kamil, adam, paulina } = HR_CAST;

/** Pn–pt bieżącego tygodnia; `pick` zwraca stan dnia roboczego (święto = „off”). */
function week(pick: (day: string) => TeamWeekState): TeamWeekDay[] {
  const monday = mondayOf(warsawToday());
  return [0, 1, 2, 3, 4].map((offset) => {
    const day = addDays(monday, offset);
    const working = harnessWorkDays(day.slice(0, 7)).includes(day);
    return { date: day, state: working ? pick(day) : "off", half_day: null };
  });
}

function bonus(id: number, amount: string, status: TeamBonusItem["status"]): TeamBonusItem {
  return {
    id,
    amount,
    currency: "PLN",
    category_label: "Rekruter",
    status,
    period_year: 2091,
    period_month: 11,
    eligible_on: null,
    description: "Placement (Bank Przykładowy)",
  };
}

function base(person: HarnessPerson): TeamPerson {
  return {
    user_id: person.id,
    name: person.name,
    job_title: person.jobTitle,
    employment_type: "b2b",
    employment_status: "active",
    last_working_day: null,
    today: { absent: false },
    covering_for: [],
    week: week(() => "work"),
    leave: { has_pool: false, has_paid_pool: false, remaining_days: null, planned_days: "0.0", pending_days: "0.0" },
    month: { hours: 0, status: "draft", timesheet_id: null },
    timesheet_required: true,
    bonuses: null,
    to_decide: { leave_requests: [], timesheets: [] },
  };
}

function harnessTeam(withBonuses: boolean): MyTeam {
  const today = warsawToday();
  const month = today.slice(0, 7);
  const [year, monthNumber] = month.split("-").map(Number);
  const norm = harnessWorkDays(month).length * 8;
  const later = harnessWorkDays(month).filter((day) => day > today);
  const ewaUntil = later[1] ?? shiftDay(today, 3);
  // „brak dd.mm” (22.10.2026): ostatni dzień roboczy przed dziś bez wpisu u Oli.
  const olaMissing = harnessWorkDays(month).filter((day) => day < today).slice(-1);
  const all: TeamPerson[] = [
    {
      ...base(ola),
      covering_for: [ewa.name],
      // B2B (D5): zgłoszone przerwy wchodzą od razu — nic nie czeka na decyzję.
      // Wiersz puli z zerem (umowa bez płatnych dni): bez „zostało 0 dni”.
      leave: {
        has_pool: true,
        has_paid_pool: false,
        remaining_days: "0.0",
        planned_days: "8.0",
        pending_days: "0.0",
      },
      month: {
        hours: Math.round(norm * 0.7),
        status: "draft",
        timesheet_id: 5101,
        missing_dates: olaMissing,
      },
      bonuses: {
        count: 2,
        proposals: 1,
        totals: [{ currency: "PLN", amount: "3000.00" }],
        items: [bonus(7101, "2000.00", "proposed"), bonus(7102, "1000.00", "assigned")],
      },
    },
    {
      ...base(ewa),
      today: {
        absent: true,
        until: ewaUntil,
        half_day: null,
        leave_type: "vacation",
        // Słowa formy (D4): na B2B „przerwa w świadczeniu usług”, nie urlop.
        leave_type_label: "Przerwa w świadczeniu usług",
        substitute_name: ola.name,
      },
      week: week((day) => (day >= today && day <= ewaUntil ? "absent" : "work")),
      leave: { has_pool: false, has_paid_pool: false, remaining_days: null, planned_days: "2.0", pending_days: "0.0" },
      month: { hours: Math.round(norm * 0.6), status: "draft", timesheet_id: 5102 },
      bonuses: {
        count: 1,
        proposals: 0,
        totals: [{ currency: "PLN", amount: "1500.00" }],
        items: [bonus(7103, "1500.00", "assigned")],
      },
    },
    {
      ...base(tomasz),
      employment_status: "offboarding",
      last_working_day: shiftDay(today, 40),
      // Dziś w delegacji (wyjątek obecności z „Mojego miesiąca”, nie nieobecność).
      week: week((day) => (day === today ? "business_trip" : "work")),
      month: { hours: norm, status: "submitted", timesheet_id: 5103 },
      bonuses: { count: 0, proposals: 0, totals: [], items: [] },
      to_decide: {
        leave_requests: [],
        timesheets: [
          {
            id: 5103,
            year,
            month: monthNumber,
            submitted_at: `${shiftDay(today, -2)}T09:00:00+02:00`,
            link: `/people/approvals?kind=timesheet&year=${year}&month=${monthNumber}&user=${tomasz.id}`,
          },
        ],
      },
    },
    {
      ...base(julia),
      employment_type: "uop",
      leave: { has_pool: true, has_paid_pool: true, remaining_days: "14.0", planned_days: "0.0", pending_days: "5.0" },
      month: { hours: Math.round(norm * 0.75), status: "draft", timesheet_id: 5104 },
      bonuses: { count: 0, proposals: 0, totals: [], items: [] },
      // Umowa o pracę: wniosek urlopowy czeka na akceptację przełożonej.
      to_decide: {
        leave_requests: [
          {
            id: "harness-leave-1",
            start_date: shiftDay(today, 30),
            end_date: shiftDay(today, 36),
            half_day: null,
            leave_type_label: "Urlop wypoczynkowy",
            days_total: "5.0",
            created_at: `${shiftDay(today, -5)}T09:00:00+02:00`,
          },
        ],
        timesheets: [],
      },
    },
    {
      ...base(adam),
      employment_type: "zlecenie",
      // Student na zleceniu (D8): sam znacznik, bez dat zwolnienia ze składek.
      student: true,
      week: week((day) => (day === addDays(mondayOf(today), 3) ? "remote" : "work")),
      timesheet_required: false,
      month: null,
      bonuses: { count: 0, proposals: 0, totals: [], items: [] },
    },
  ];
  const people = withBonuses ? all : all.map((person) => ({ ...person, bonuses: null }));
  return {
    manager: { user_id: marta.id, name: marta.name },
    is_own: withBonuses,
    today,
    modules: { leave: true, time: true, payroll: true },
    sees_bonuses: withBonuses,
    month: { year, month: monthNumber, norm_hours: norm, deadline: `${month}-05` },
    week: { days: week(() => "work").map((day) => ({ date: day.date, kind: day.state === "off" ? "holiday" : "work" })) },
    people,
    stats: {
      people: people.length,
      absent_today: 1,
      leave_requests: 1,
      timesheets: 1,
      bonus_proposals: withBonuses ? 1 : null,
    },
  };
}

function prepare(params: URLSearchParams) {
  const as = pickState(params.get("as"), AS, "manager");
  const client = harnessQueryClient();
  const config: HrConfig =
    as === "hr"
      ? hrConfig({ people_admin: true })
      : hrConfig({ is_manager: true, direct_reports: 5 });
  client.setQueryData(hrKeys.config, config);
  client.setQueryData(hrKeys.counts, { approvals: 2, cases: null });
  if (as === "hr") {
    client.setQueryData(teamKeys.team(marta.id), harnessTeam(false));
    client.setQueryData(teamKeys.managers, [
      { user_id: kamil.id, name: kamil.name, reports: 2 },
      { user_id: marta.id, name: marta.name, reports: 5 },
    ]);
  } else {
    client.setQueryData(teamKeys.team(null), harnessTeam(true));
  }
  return {
    user: as === "hr" ? { ...paulina, grants: ["people_admin" as const] } : marta,
    client,
    value: { as, config },
  };
}

export default function HrTeamPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { as, config } = ready.value;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Ludzie → Mój zespół"
      note="Dane i kwoty fikcyjne, bez zapytań. Premie bez stawek (D2); rodzaj nieobecności widzi krąg D6."
      states={STATES}
      current={as}
      param="as"
    >
      <div className="space-y-4">
        <PageHeader
          title="Mój zespół"
          description="Kto jest dziś, co czeka na Twoją decyzję i jak idzie miesiąc."
          density="compact"
        />
        <PeopleSectionNav config={config} active="team" />
        <TeamScreen config={config} initialManager={as === "hr" ? marta.id : null} />
      </div>
    </HrHarnessShell>
  );
}
