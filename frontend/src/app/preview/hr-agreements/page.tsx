"use client";

/**
 * Harness „Umowy z ludźmi” (etap 5, E5, makieta „Umowa zlecenia”).
 *
 * Prawdziwe komponenty na zasianym cache, ZERO zapytań (`hr-harness.tsx`).
 * Daty liczą się od bieżącego miesiąca przeglądarki.
 *
 * Stany (`?state=`):
 * - `person` (domyślnie) — Kadry w kartotece Celiny (zlecenie): umowa
 *   podpisana w Autenti, aneks podpisany ręcznie, kolejny aneks czeka na podpis;
 * - `new` — okno „Nowa umowa albo aneks” z listą wzorów i tym, co NEXUS zrobi
 *   po podpisie;
 * - `issues` — Ola (B2B): szkic po nieudanej wysyłce do Autenti i umowa
 *   podpisana, która nie przeszła do kartoteki (zamknięty miesiąc płac);
 * - `payroll` — Płace oglądają te same umowy bez akcji;
 * - `templates` — Ustawienia → Kadry → „Wzory umów” z wersjami (admin).
 * Zapisy i pobrania blokuje harness.
 */

import { AgreementDialog } from "@/components/hr/people/agreements/AgreementDialog";
import { AgreementTemplatesCard } from "@/components/hr/people/agreements/AgreementTemplatesCard";
import { PersonAgreementsSection } from "@/components/hr/people/agreements/PersonAgreementsSection";
import { hrKeys } from "@/lib/api/hr";
import { agreementKeys } from "@/lib/api/hr-agreements";

import { HR_CAST } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
  type HarnessUser,
} from "../hr-harness";
import {
  ACTIVE_TEMPLATES,
  CELINA,
  OLA,
  PEOPLE,
  SETTINGS,
  TEMPLATES,
  celinaAgreements,
  olaAgreements,
} from "./fixtures";

const STATE_KEYS = ["person", "new", "issues", "payroll", "templates"] as const;
type State = (typeof STATE_KEYS)[number];

const STATES = [
  { key: "person", label: "Kadry: umowy osoby" },
  { key: "new", label: "Nowa umowa albo aneks" },
  { key: "issues", label: "Do wyjaśnienia" },
  { key: "payroll", label: "Płace: podgląd" },
  { key: "templates", label: "Wzory umów" },
] as const;

const NOTES: Record<State, string> = {
  person: "Dane fikcyjne, bez zapytań. Ogląda Paulina z Kadr — podpis przez Autenti albo ręcznie ze skanem.",
  new: "Dane fikcyjne, bez zapytań. Wzór wybiera formę; minimum zlecenia z Ustawień Płac.",
  issues: "Dane fikcyjne, bez zapytań. Autenti nie przyjęło wysyłki, a podpisana umowa trafiła na zamknięty miesiąc płac.",
  payroll: "Dane fikcyjne, bez zapytań. Płace widzą umowy i stawki, ale ich nie zmieniają.",
  templates: "Dane fikcyjne, bez zapytań. Pliki Word od Kadr z wersjami; treści prawnej NEXUS nie pisze.",
};

function prepare(params: URLSearchParams) {
  const state = pickState(params.get("state"), STATE_KEYS, "person");
  const client = harnessQueryClient();
  let user: HarnessUser = { ...HR_CAST.paulina, grants: ["people_admin"] };
  client.setQueryData(hrKeys.people, PEOPLE);
  client.setQueryData(agreementKeys.templates(true), ACTIVE_TEMPLATES);
  client.setQueryData(agreementKeys.templates(false), TEMPLATES);
  client.setQueryData(agreementKeys.settings, SETTINGS);
  if (state === "issues") {
    client.setQueryData(agreementKeys.person(OLA.id), olaAgreements());
  } else if (state === "payroll") {
    user = { ...HR_CAST.piotr, grants: ["payroll"] };
    client.setQueryData(agreementKeys.person(CELINA.id), celinaAgreements(false));
  } else if (state === "templates") {
    user = HR_CAST.admin;
  } else {
    client.setQueryData(agreementKeys.person(CELINA.id), celinaAgreements());
  }
  return { user, client, value: { state } };
}

export default function HrAgreementsPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { state } = ready.value;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Umowy z ludźmi"
      note={NOTES[state]}
      states={STATES}
      current={state}
    >
      {state === "templates" ? (
        <AgreementTemplatesCard isAdmin />
      ) : state === "issues" ? (
        <PersonAgreementsSection userId={OLA.id} enabled />
      ) : state === "new" ? (
        <>
          <PersonAgreementsSection userId={CELINA.id} enabled />
          <AgreementDialog overview={celinaAgreements()} onClose={() => undefined} />
        </>
      ) : (
        <PersonAgreementsSection userId={CELINA.id} enabled />
      )}
    </HrHarnessShell>
  );
}
