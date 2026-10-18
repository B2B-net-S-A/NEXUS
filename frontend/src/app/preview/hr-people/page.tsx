"use client";

/**
 * Harness „Ludzie → Katalog” z listą rozjazdów kartoteka ↔ konto NEXUSA
 * (decyzja Artura 19.10.2026: „Konto decyduje + lista rozjazdów”).
 *
 * Prawdziwe `PeopleSectionNav` + `PeopleDirectory` na zasianym cache, ZERO
 * zapytań (`hr-harness.tsx`).
 *
 * Stany (`?as=` — kto ogląda):
 * - `hr` (domyślnie) — Kadry bez Płac: pasek „Rozjazdy z kontami NEXUSA: 3”
 *   (konto wyłączone przy aktywnej kartotece — z dwiema osobami pod sobą, konto
 *   włączone przy zamkniętej, konto bez kartoteki), liczniki „do uzupełnienia”,
 *   „Wyrównaj wg konta” z potwierdzeniem; przy Kacprze „do uzupełnienia”;
 * - `finance` — Finanse (Płace bez Kadr): ten sam pasek, bez „Dodaj osobę”;
 * - `colleague` — rekruterka: wizytówki, bez paska.
 * Zapis „Wyrównaj” blokuje harness.
 */

import { PageHeader } from "@/components/ds/PageHeader";
import { PeopleDirectory } from "@/components/hr/people/PeopleDirectory";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";
import {
  hrKeys,
  type AccountMismatches,
  type HrConfig,
  type Person,
  type PersonFull,
} from "@/lib/api/hr";
import { leaveKeys } from "@/lib/api/hr-leave";

import { HR_CAST, hrConfig } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";
import { harnessDirectory } from "../hr-person/fixtures";

const AS = ["hr", "finance", "colleague"] as const;

const STATES = [
  { key: "hr", label: "Kadry: rozjazdy z kontami" },
  { key: "finance", label: "Finanse" },
  { key: "colleague", label: "Rekruterka (wizytówki)" },
] as const;

const { paulina, piotr, ewa, kacper, julia, marta } = HR_CAST;

/** Pełne wiersze katalogu — Kadry bez Płac dostają je bez formy umowy. */
function fullRows(withForm: boolean): Person[] {
  return harnessDirectory().items.map((card): PersonFull => ({
    ...card,
    scope: "full",
    employment_type: withForm ? "b2b" : null,
    employment_type_pending: false,
    hired_on: null,
    work_start_date: null,
    last_working_day: null,
    timesheet_required: true,
    can_log_overtime: false,
    roles: ["recruiter"],
  }));
}

function directory(withForm: boolean): { items: Person[]; total: number } {
  const kacperRow: PersonFull = {
    user_id: kacper.id,
    name: kacper.name,
    email: kacper.email,
    job_title: null,
    department: null,
    phone: null,
    default_location: "onsite",
    employment_status: "active",
    manager_user_id: null,
    manager_name: null,
    scope: "full",
    employment_type: withForm ? "b2b" : null,
    employment_type_pending: true,
    manager_pending: true,
    hired_on: null,
    work_start_date: null,
    last_working_day: null,
    timesheet_required: true,
    can_log_overtime: false,
    roles: ["recruiter"],
  };
  const items = [...fullRows(withForm), kacperRow].sort((a, b) =>
    a.name.localeCompare(b.name, "pl"),
  );
  return { items, total: items.length };
}

const MISMATCHES: AccountMismatches = {
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

function prepare(params: URLSearchParams) {
  const as = pickState(params.get("as"), AS, "hr");
  const config: HrConfig =
    as === "hr"
      ? hrConfig({ people_admin: true })
      : as === "finance"
        ? hrConfig({ payroll: true, has_profile: false })
        : hrConfig();
  const client = harnessQueryClient();
  client.setQueryData(hrKeys.config, config);
  client.setQueryData(hrKeys.counts, { approvals: 0, cases: null });
  const people = as === "colleague" ? harnessDirectory() : directory(as === "finance");
  client.setQueryData(hrKeys.people, people);
  // Plakietki nieobecności katalogu — dziś nikt nie jest nieobecny.
  const ids = people.items.map((row) => row.user_id).sort((a, b) => a - b).join(",");
  client.setQueryData(leaveKeys.absence(ids, null), { on: "", items: [] });
  client.setQueryData(hrKeys.accountMismatches, MISMATCHES);
  const viewer =
    as === "hr"
      ? { ...paulina, grants: ["people_admin" as const] }
      : as === "finance"
        ? { ...piotr, grants: ["payroll" as const] }
        : ewa;
  return { user: viewer, client, value: { as, config } };
}

export default function HrPeoplePreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { as, config } = ready.value;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Ludzie → Katalog"
      note="Dane fikcyjne, bez zapytań. Kartoteka idzie za kontem NEXUSA; lista zbiera rozjazdy do wyrównania."
      states={STATES}
      current={as}
      param="as"
    >
      <div className="space-y-4">
        <PageHeader
          title="Ludzie"
          description="Kto u nas pracuje, komu podlega i gdzie domyślnie pracuje."
          density="compact"
        />
        <PeopleSectionNav config={config} active="directory" />
        <PeopleDirectory config={config} />
      </div>
    </HrHarnessShell>
  );
}
