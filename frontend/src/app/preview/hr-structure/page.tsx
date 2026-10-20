"use client";

/**
 * Harness „Ludzie → Struktura” (etap 2, makieta „Struktura”, D4 i D7).
 *
 * Prawdziwe `PeopleSectionNav` + `StructureScreen` na zasianym cache, ZERO
 * zapytań (`hr-harness.tsx`). Ogląda Paulina (Kadry i Płace — formę umowy
 * w Strukturze widzą admin i Finanse, 19.10.2026).
 *
 * Stany (`?state=`):
 * - `tree` (domyślnie) — Front office (head Kamil) z Martą, która odchodzi
 *   w przyszłym miesiącu i ma czworo ludzi (przejmie ich Kamil), rozjazd
 *   z Microsoft 365 przy Oli, Kacper bez koordynatora z podpowiedzią „head
 *   pionu” — jego kartotekę założył automat z konta (forma i przełożony „do
 *   uzupełnienia”); Back office (head Piotr); Paulina bez pionu;
 * - `hr-only` — to samo drzewo oczami Kadr bez Płac: bez formy umowy;
 * - `empty` — nikt nie ma jeszcze kartoteki;
 * - `big` — jak prod 20.10.2026: piony puste, 44 osoby „Bez pionu” (szef →
 *   dwie osoby → po ~20 osób bez własnych ludzi); podwładni stoją w kolumnie
 *   pod przełożonym, schemat otwiera się na korzeniu.
 * Zaznaczenie osób i okna „Zmień koordynatora”, „Ustaw pion”, „Headowie
 * pionów” otwierają się bez zapytań; zapisy blokuje harness.
 *
 * Makieta 19.10.2026: domyślnie „Schemat” — drzewo kart per pion (przeciągnięcie
 * karty na inną = zmiana przełożonego z potwierdzeniem, menu ⋯ karty), „Lista”
 * to dotychczasowy widok z zaznaczaniem; panel „Do uporządkowania” zbiera
 * odejście Marty, rozjazd M365, podpowiedź dla Kacpra i osoby bez pionu.
 */

import { PageHeader } from "@/components/ds/PageHeader";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";
import { StructureScreen } from "@/components/hr/structure/StructureScreen";
import { hrKeys, type Division, type EmploymentType, type HrConfig } from "@/lib/api/hr";
import {
  structureKeys,
  type HrStructure,
  type StructurePerson,
} from "@/lib/api/hr-structure";
import { warsawToday } from "@/lib/warsaw-date";
import { shiftMonth } from "@/lib/date-pl";

import { HR_CAST, harnessWorkDays, hrConfig, type HarnessPerson } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";

const STATE_KEYS = ["tree", "hr-only", "empty", "big"] as const;

const STATES = [
  { key: "tree", label: "Drzewo z pionami" },
  { key: "hr-only", label: "Kadry bez Płac (bez formy)" },
  { key: "empty", label: "Bez kartotek" },
  { key: "big", label: "44 osoby bez pionu" },
] as const;

const { kamil, marta, ola, ewa, tomasz, julia, adam, kacper, piotr, natalia, zofia, paulina } =
  HR_CAST;

function row(
  person: HarnessPerson,
  division: Division | null,
  manager: HarnessPerson | null,
  type: EmploymentType = "b2b",
): StructurePerson {
  return {
    user_id: person.id,
    name: person.name,
    email: person.email,
    job_title: person.jobTitle,
    department: person.department,
    employment_type: type,
    employment_status: "active",
    division,
    manager_user_id: manager?.id ?? null,
    manager_name: manager?.name ?? null,
    manager_state: manager ? "ok" : "none",
    reports: 0,
    leaving: null,
    m365_hint: null,
    suggested_manager: null,
  };
}

function harnessStructure(): HrStructure {
  const next = shiftMonth(warsawToday().slice(0, 7), 1);
  const lastDay = harnessWorkDays(next).at(-1) ?? `${next}-28`;
  const people: StructurePerson[] = [
    { ...row(kamil, "front_office", null), reports: 2 },
    {
      ...row(marta, "front_office", kamil, "uop"),
      reports: 4,
      employment_status: "offboarding",
      leaving: {
        case_id: 4202,
        status: "active",
        last_working_day: lastDay,
        reports_receiver_user_id: kamil.id,
        reports_receiver_name: kamil.name,
        reports_handover_status: "planned",
      },
    },
    {
      ...row(ola, "front_office", marta),
      m365_hint: { upn: kamil.email, user_id: kamil.id, name: kamil.name, can_accept: true },
    },
    row(ewa, "front_office", marta),
    row(tomasz, "front_office", marta),
    // Uczennica/studentka na zleceniu (D8): plakietka „składki od …”.
    { ...row(julia, "front_office", marta, "zlecenie"), student: true, contributions_from: "2027-07-01" },
    row(adam, "front_office", kamil),
    {
      ...row(kacper, "front_office", null),
      suggested_manager: { user_id: kamil.id, name: kamil.name },
      // Kartoteka założona z konta NEXUSA (19.10.2026).
      employment_type_pending: true,
      manager_pending: true,
    },
    { ...row(piotr, "back_office", null), reports: 1 },
    row(natalia, "back_office", piotr),
    {
      ...row(zofia, "back_office", null, "zlecenie"),
      suggested_manager: { user_id: piotr.id, name: piotr.name },
    },
    row(paulina, null, null, "uop"),
  ];
  return {
    people,
    outside_managers: [],
    divisions: [
      { key: "front_office", label: "Front office", head_user_id: kamil.id, head_name: kamil.name, head_active: true },
      { key: "back_office", label: "Back office", head_user_id: piotr.id, head_name: piotr.name, head_active: true },
    ],
    total: people.length,
    without_manager: 3,
    inactive_manager: 0,
    m365_mismatches: 1,
  };
}

const FIRST = ["Anna", "Bartosz", "Celina", "Dawid", "Ewelina", "Filip", "Grażyna", "Hubert", "Iga", "Jan", "Kinga"];
const LAST = ["Przykładowa", "Testowy", "Makietowa", "Fikcyjny"];

/** Prod 20.10.2026 w fikcyjnych danych: 44 osoby bez pionu, drzewo płaskie. */
function bigStructure(): HrStructure {
  const base = (id: number, name: string, extra: Partial<StructurePerson> = {}): StructurePerson => ({
    ...row({ ...kamil, id, name, email: `osoba${id}@example.com`, jobTitle: "Konsultant" }, null, null),
    ...extra,
  });
  const boss = base(900, "Szef Przykładowy", { reports: 2, job_title: "Prezes" });
  const leads = [
    base(901, "Lidia Prowadząca", { reports: 21, job_title: "Head of Recruitment" }),
    base(902, "Oskar Prowadzący", { reports: 18, job_title: "Head of Delivery" }),
  ].map((lead) => ({ ...lead, manager_user_id: boss.user_id, manager_name: boss.name, manager_state: "ok" as const }));
  const team = Array.from({ length: 39 }, (_, i) => {
    const lead = i < 21 ? leads[0] : leads[1];
    return base(1000 + i, `${FIRST[i % FIRST.length]} ${LAST[Math.floor(i / FIRST.length)]}`, {
      manager_user_id: lead.user_id,
      manager_name: lead.name,
      manager_state: "ok",
      employment_type: i % 3 ? "b2b" : "uop",
    });
  });
  const loose = [0, 1].map((i) => base(1100 + i, `Bez Koordynatora ${i + 1}`));
  const people = [boss, ...leads, ...team, ...loose];
  return {
    people,
    outside_managers: [],
    divisions: [
      { key: "front_office", label: "Front office", head_user_id: null, head_name: null, head_active: false },
      { key: "back_office", label: "Back office", head_user_id: null, head_name: null, head_active: false },
    ],
    total: people.length,
    without_manager: loose.length,
    inactive_manager: 0,
    m365_mismatches: 0,
  };
}

function prepare(params: URLSearchParams) {
  const state = pickState(params.get("state"), STATE_KEYS, "tree");
  const hrOnly = state === "hr-only";
  const config: HrConfig = hrConfig({ people_admin: true, payroll: !hrOnly, has_profile: true });
  const tree = state === "big" ? bigStructure() : harnessStructure();
  // Kadry bez Płac: serwer nie przysyła formy ani pól od niej zależnych.
  const shown: HrStructure = hrOnly
    ? {
        ...tree,
        people: tree.people.map((person) => ({
          ...person,
          employment_type: null,
          student: null,
          contributions_from: null,
        })),
      }
    : tree;
  const client = harnessQueryClient();
  client.setQueryData(hrKeys.config, config);
  client.setQueryData(hrKeys.counts, { approvals: 3, cases: null });
  client.setQueryData(
    structureKeys.all,
    state === "empty"
      ? { ...tree, people: [], total: 0, without_manager: 0, m365_mismatches: 0 }
      : shown,
  );
  return {
    user: {
      ...paulina,
      grants: hrOnly ? ["people_admin" as const] : ["people_admin" as const, "payroll" as const],
    },
    client,
    value: { state, config },
  };
}

export default function HrStructurePreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { state, config } = ready.value;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Ludzie → Struktura"
      note="Dane fikcyjne, bez zapytań. Zmiana przełożonego działa od razu; Microsoft 365 i head pionu tylko podpowiadają."
      states={STATES}
      current={state}
    >
      <div className="space-y-4">
        <PageHeader
          title="Struktura"
          description="Piony, przełożeni i koordynatorzy. Zmiana działa od razu."
          density="compact"
        />
        <PeopleSectionNav config={config} active="structure" />
        <StructureScreen config={config} />
      </div>
    </HrHarnessShell>
  );
}
