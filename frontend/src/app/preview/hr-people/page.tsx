"use client";

/**
 * Harness „Ludzie → Katalog” z listą rozjazdów kartoteka ↔ konto NEXUSA
 * (decyzja Artura 19.10.2026: „Konto decyduje + lista rozjazdów”).
 *
 * Prawdziwe `PeopleSectionNav` + `PeopleDirectory` na zasianym cache, ZERO
 * zapytań (`hr-harness.tsx`).
 *
 * Stany (`?as=` — kto ogląda):
 * - `hr` (domyślnie) — Kadry bez Płac: pasek „Do wyrównania” z nazwanymi
 *   pozycjami (konto wyłączone przy aktywnej kartotece — z dwiema osobami pod
 *   sobą, konto włączone przy zamkniętej, konto bez kartoteki, Kacper: forma
 *   i przełożony), „Przejrzyj po kolei” i „Wyrównaj wg konta” z potwierdzeniem;
 *   katalog bez kolumny „Forma” (Kadry bez Płac nie widzą formy);
 * - `finance` — Finanse (Płace bez Kadr): ten sam pasek i forma jako pigułka,
 *   bez „Dodaj osobę”;
 * - `colleague` — rekruterka: wizytówki, bez paska i bez formy.
 *
 * Makieta 19.10.2026: chipy działów z licznikami, grupy po dziale, kolumna
 * „Dziś” (nieobecność do…, delegacja, odchodzi, w pracy), mini-awatar przełożonego
 * i staż. Nieobecności bez rodzaju (D6).
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
  type PersonToday,
} from "@/lib/api/hr";
import { warsawToday } from "@/lib/warsaw-date";

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

function directory(withForm: boolean): { items: Person[]; total: number } {
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
function cards(): { items: Person[]; total: number } {
  const base = harnessDirectory({ [HR_CAST.tomasz.id]: "offboarding" });
  return {
    ...base,
    items: base.items.map((card) => ({ ...card, today: TODAY[card.user_id] ?? null })),
  };
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
  const people = as === "colleague" ? cards() : directory(as === "finance");
  client.setQueryData(hrKeys.people, people);
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
          description="Kto z nami współpracuje, kto koordynuje i kto jest dziś dostępny."
          density="compact"
        />
        <PeopleSectionNav config={config} active="directory" />
        <PeopleDirectory config={config} />
      </div>
    </HrHarnessShell>
  );
}
