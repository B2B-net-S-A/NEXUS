/**
 * Fikcyjna struktura do harnessów „Ludzi” (`/preview/hr-structure`,
 * `/preview/hr-people` — sekcja „Struktura” w „Porządkach”).
 */

import type { Division, EmploymentType } from "@/lib/api/hr";
import type { HrStructure, StructurePerson } from "@/lib/api/hr-structure";
import { warsawToday } from "@/lib/warsaw-date";
import { shiftMonth } from "@/lib/date-pl";

import { HR_CAST, harnessWorkDays, type HarnessPerson } from "../hr-fixtures";

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

export function harnessStructure(): HrStructure {
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
export function bigStructure(): HrStructure {
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
