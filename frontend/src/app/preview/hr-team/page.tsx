"use client";

/**
 * Harness „Ludzie → Mój zespół” (etap 2, makieta „Mój zespół”, D6).
 *
 * Prawdziwe `PeopleSectionNav` + `TeamScreen` na zasianym cache, ZERO zapytań
 * (`hr-harness.tsx`). Zespół Marty: większość na B2B albo zleceniu (bez puli —
 * kolumna „Nieobecności” pokazuje zaplanowane dni), Julia na UoP z pulą.
 *
 * Stany (`?as=`):
 * - `manager` (domyślnie) — Marta o swoich ludziach: Ewa na urlopie (rodzaj
 *   widzi przełożona, D6), Ola ją zastępuje, premie z kwotą bez stawek,
 *   wniosek i timesheet do decyzji;
 * - `hr` — Paulina (Kadry bez Płac) ogląda zespół Marty z wyboru przełożonego:
 *   bez kolumny premii.
 */

import { PageHeader } from "@/components/ds/PageHeader";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";
import { TeamScreen } from "@/components/hr/team/TeamScreen";
import { hrKeys, type HrConfig } from "@/lib/api/hr";
import { teamKeys, type MyTeam, type TeamPerson } from "@/lib/api/hr-team";
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
    leave: { has_pool: false, remaining_days: null, planned_days: "0.0", pending_days: "0.0" },
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
  const all: TeamPerson[] = [
    {
      ...base(ola),
      covering_for: [ewa.name],
      // B2B (D5): zgłoszone przerwy wchodzą od razu — nic nie czeka na decyzję.
      leave: { has_pool: false, remaining_days: null, planned_days: "8.0", pending_days: "0.0" },
      month: { hours: Math.round(norm * 0.7), status: "draft", timesheet_id: 5101 },
      bonuses: {
        count: 2,
        proposals: 1,
        totals: [{ currency: "PLN", amount: "3000.00" }],
        items: [],
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
      leave: { has_pool: false, remaining_days: null, planned_days: "2.0", pending_days: "0.0" },
      month: { hours: Math.round(norm * 0.6), status: "draft", timesheet_id: 5102 },
      bonuses: {
        count: 1,
        proposals: 0,
        totals: [{ currency: "PLN", amount: "1500.00" }],
        items: [],
      },
    },
    {
      ...base(tomasz),
      employment_status: "offboarding",
      month: { hours: norm, status: "submitted", timesheet_id: 5103 },
      bonuses: { count: 0, proposals: 0, totals: [], items: [] },
      to_decide: {
        leave_requests: [],
        timesheets: [
          {
            id: 5103,
            year,
            month: monthNumber,
            link: `/people/approvals?kind=timesheet&year=${year}&month=${monthNumber}&user=${tomasz.id}`,
          },
        ],
      },
    },
    {
      ...base(julia),
      employment_type: "uop",
      leave: { has_pool: true, remaining_days: "14.0", planned_days: "0.0", pending_days: "5.0" },
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
          },
        ],
        timesheets: [],
      },
    },
    {
      ...base(adam),
      employment_type: "zlecenie",
      // Student na zleceniu (D8): plakietka „składki od …”.
      student: true,
      contributions_from: "2027-07-01",
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
          description="Kto jest dziś, nieobecności, bieżący miesiąc, premie i sprawy do decyzji."
          density="compact"
        />
        <PeopleSectionNav config={config} active="team" />
        <TeamScreen config={config} initialManager={as === "hr" ? marta.id : null} />
      </div>
    </HrHarnessShell>
  );
}
