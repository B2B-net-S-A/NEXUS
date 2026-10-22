"use client";

/**
 * Harness „Ludzie → Katalog: Schemat” (dawna zakładka „Struktura”, etap 2,
 * D4 i D7; od 22.10.2026 widok `?view=schemat` katalogu).
 *
 * Prawdziwe `PeopleHeaderActions` + `PeopleSectionNav` + `PeopleDirectory`
 * otwarte na schemacie, na zasianym cache, ZERO zapytań (`hr-harness.tsx`).
 * Ogląda Paulina (Kadry i Płace — formę umowy widzą admin i Finanse, 19.10.2026).
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
 *
 * Schemat: drzewo kart per pion (przeciągnięcie karty na inną = zmiana
 * koordynatora z potwierdzeniem, menu ⋯ karty), „Headowie pionów”. „Lista”
 * katalogu zaznacza osoby i otwiera „Ustaw pion” / „Zmień koordynatora”;
 * „Porządki” w nagłówku zbierają odejście Marty, rozjazd M365, podpowiedź
 * dla Kacpra, osoby bez pionu i (w `tree`) rozjazdy z kontami. Okna otwierają
 * się bez zapytań; zapisy blokuje harness.
 */

import { PageHeader } from "@/components/ds/PageHeader";
import { PeopleDirectory } from "@/components/hr/people/PeopleDirectory";
import { PeopleHeaderActions } from "@/components/hr/people/PeopleHeaderActions";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";
import { hrKeys, type HrConfig, type Person } from "@/lib/api/hr";
import { structureKeys, type HrStructure } from "@/lib/api/hr-structure";

import { HR_CAST, hrConfig } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";
import { HARNESS_MISMATCHES, harnessPeopleDirectory } from "../hr-people/fixtures";
import { bigStructure, harnessStructure } from "./fixtures";

const { paulina } = HR_CAST;

/** Wiersze katalogu z osób struktury (ten sam zbiór co schemat). */
function directoryFrom(structure: HrStructure, withForm: boolean): { items: Person[]; total: number } {
  const known = harnessPeopleDirectory(withForm).items;
  const byId = new Map(known.map((person) => [person.user_id, person]));
  const items = structure.people.map(
    (person): Person =>
      byId.get(person.user_id) ?? {
        user_id: person.user_id,
        name: person.name,
        email: person.email,
        job_title: person.job_title,
        department: person.department,
        phone: null,
        default_location: "remote",
        employment_status: person.employment_status,
        manager_user_id: person.manager_user_id,
        manager_name: person.manager_name,
        scope: "card",
      },
  );
  return { items, total: items.length };
}

const STATE_KEYS = ["tree", "hr-only", "empty", "big"] as const;

const STATES = [
  { key: "tree", label: "Drzewo z pionami" },
  { key: "hr-only", label: "Kadry bez Płac (bez formy)" },
  { key: "empty", label: "Bez kartotek" },
  { key: "big", label: "44 osoby bez pionu" },
] as const;

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
  const structure: HrStructure =
    state === "empty"
      ? { ...tree, people: [], total: 0, without_manager: 0, m365_mismatches: 0 }
      : shown;
  client.setQueryData(structureKeys.all, structure);
  client.setQueryData(hrKeys.people, directoryFrom(structure, !hrOnly));
  client.setQueryData(
    hrKeys.accountMismatches,
    state === "tree" ? HARNESS_MISMATCHES : { items: [], total: 0, pending: { employment_type: 0, manager: 0 } },
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
      title="Ludzie → Katalog: Schemat"
      note="Dane fikcyjne, bez zapytań. Zmiana przełożonego działa od razu; Microsoft 365 i head pionu tylko podpowiadają."
      states={STATES}
      current={state}
    >
      <div className="space-y-4">
        <PageHeader
          title="Ludzie"
          description="Kto z nami współpracuje, kto koordynuje i kto jest dziś dostępny."
          density="compact"
          actions={<PeopleHeaderActions config={config} />}
        />
        <PeopleSectionNav config={config} active="directory" />
        <PeopleDirectory config={config} defaultView="schemat" />
      </div>
    </HrHarnessShell>
  );
}
