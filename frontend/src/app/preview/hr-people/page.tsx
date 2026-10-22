"use client";

/**
 * Harness „Ludzie → Katalog” z „Porządkami” (22.10.2026; wcześniej żółty pasek
 * „Do wyrównania” — decyzja Artura 19.10.2026: „Konto decyduje + lista
 * rozjazdów”).
 *
 * Prawdziwe `PeopleHeaderActions` + `PeopleSectionNav` + `PeopleDirectory` na
 * zasianym cache, ZERO zapytań (`hr-harness.tsx`).
 *
 * Stany (`?as=` — kto ogląda):
 * - `hr` (domyślnie) — Kadry bez Płac: „Porządki · N” w nagłówku, w panelu
 *   sekcja „Struktura” (odejście Marty, M365, podpowiedź „head pionu”, osoby
 *   bez pionu) i „Konta i kartoteki” (konto wyłączone przy aktywnej
 *   kartotece — z dwiema osobami pod sobą, konto włączone przy zamkniętej,
 *   konto bez kartoteki, Kacper: forma i koordynator) z „Przejrzyj po kolei”
 *   i „Wyrównaj wg konta”; katalog bez kolumny „Forma” (Kadry bez Płac nie
 *   widzą formy), przełącznik „Lista | Schemat” (`?view=schemat`);
 * - `finance` — Finanse (Płace bez Kadr): „Porządki” tylko z kontami, forma
 *   jako pigułka, bez „Dodaj osobę” i bez schematu;
 * - `colleague` — rekruterka: wizytówki, bez „Porządków” i bez formy.
 *
 * Makieta 19.10.2026: chipy działów z licznikami, grupy po dziale, kolumna
 * „Dziś” (nieobecność do…, delegacja, odchodzi, w pracy), mini-awatar
 * koordynatora i staż. Nieobecności bez rodzaju (D6). Zapisy blokuje harness.
 */

import { PageHeader } from "@/components/ds/PageHeader";
import { PeopleDirectory } from "@/components/hr/people/PeopleDirectory";
import { PeopleHeaderActions } from "@/components/hr/people/PeopleHeaderActions";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";
import { hrKeys, type HrConfig } from "@/lib/api/hr";
import { structureKeys, type HrStructure } from "@/lib/api/hr-structure";

import { HR_CAST, hrConfig } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";
import { harnessStructure } from "../hr-structure/fixtures";
import { HARNESS_MISMATCHES, harnessPeopleCards, harnessPeopleDirectory } from "./fixtures";

const AS = ["hr", "finance", "colleague"] as const;

const STATES = [
  { key: "hr", label: "Kadry: porządki i schemat" },
  { key: "finance", label: "Finanse" },
  { key: "colleague", label: "Rekruterka (wizytówki)" },
] as const;

const { paulina, piotr, ewa } = HR_CAST;

/** Kadry bez Płac: serwer nie przysyła formy ani pól od niej zależnych. */
function structureWithoutForm(): HrStructure {
  const tree = harnessStructure();
  return {
    ...tree,
    people: tree.people.map((person) => ({
      ...person,
      employment_type: null,
      student: null,
      contributions_from: null,
    })),
  };
}

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
  const people = as === "colleague" ? harnessPeopleCards() : harnessPeopleDirectory(as === "finance");
  client.setQueryData(hrKeys.people, people);
  client.setQueryData(hrKeys.accountMismatches, HARNESS_MISMATCHES);
  client.setQueryData(structureKeys.all, structureWithoutForm());
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
      note="Dane fikcyjne, bez zapytań. Kartoteka idzie za kontem NEXUSA; „Porządki” zbierają strukturę i rozjazdy z kontami."
      states={STATES}
      current={as}
      param="as"
    >
      <div className="space-y-4">
        <PageHeader
          title="Ludzie"
          description="Kto z nami współpracuje, kto koordynuje i kto jest dziś dostępny."
          density="compact"
          actions={<PeopleHeaderActions config={config} />}
        />
        <PeopleSectionNav config={config} active="directory" />
        <PeopleDirectory config={config} />
      </div>
    </HrHarnessShell>
  );
}
