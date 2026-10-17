"use client";

/**
 * Harness „Ludzie → Kartoteka osoby” (makieta 6 raportu „Ludzie w NEXUSIE”).
 *
 * Prawdziwe `PersonProfile` (strona `/people/[userId]`) z sekcjami, które
 * montuje — „Wejście i odejście”, „Płace”, „Sprzęt” — na zasianym cache,
 * ZERO zapytań (`hr-harness.tsx`). Oglądana osoba: rekruterka Ola.
 *
 * Stany (`?as=` — kto ogląda):
 * - `hr` (domyślnie) — Kadry z uprawnieniem Płace: pełna kartoteka z „Edytuj
 *   kartotekę” i „Zmień pulę”, historia stawek z „Nowa stawka od…”, premie,
 *   „Rozpocznij odejście”, sprzęt z protokołu;
 * - `manager` — przełożona bez Płac: pełna kartoteka do odczytu, premie bez
 *   stawek (serwer nie przysyła stawek, D2), bez sprzętu i bez zakładania
 *   odejścia;
 * - `colleague` — rekruterka z zespołu: wizytówka; Płace (404) i „Wejście
 *   i odejście” (403) zasiane jako odmowa serwera, więc sekcje się chowają.
 * Forma Oli (`?form=`, etap 2, D6–D9): `b2b` (domyślnie, płatne dni przerwy
 * z umowy), `zlecenie` (uczeń/student — składki od 01.07.2027, bez puli),
 * `uop` (staż do urlopu 12 lat, zaświadczenie ZUS, podpowiedź wymiaru 26 dni).
 * Okna „Edytuj kartotekę”, „Zmień pulę”, „Nowa stawka od…” i „Nowa premia”
 * otwierają się bez zapytań; zapisy blokuje harness.
 */

import { PersonProfile } from "@/components/hr/people/PersonProfile";
import type { EmploymentType, HrConfig } from "@/lib/api/hr";
import { equipmentKeys } from "@/lib/api/equipment";
import { payrollKeys, type PersonPayroll } from "@/lib/api/hr-payroll";

import { HR_CAST, HR_CONFIG_QUERY_KEY, hrConfig } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";
import { MARTA_REPORTS, closingBonuses, payrollScene } from "../hr-payroll/fixtures";
import {
  HR_PEOPLE_KEYS,
  LIFECYCLE_KEYS,
  OLA_EQUIPMENT,
  OLA_RATES,
  harnessDirectory,
  olaFull,
  personCard,
  seedHttpError,
} from "./fixtures";

const AS = ["hr", "manager", "colleague"] as const;
type As = (typeof AS)[number];
const FORMS = ["b2b", "zlecenie", "uop"] as const satisfies readonly EmploymentType[];

const STATES = [
  { key: "hr", label: "Kadry i Płace" },
  { key: "hr-zlecenie", label: "Zlecenie: student", href: "?as=hr&form=zlecenie" },
  { key: "hr-uop", label: "UoP: staż do urlopu", href: "?as=hr&form=uop" },
  { key: "manager", label: "Przełożona (bez stawek)" },
  { key: "colleague", label: "Kolega z zespołu (wizytówka)" },
] as const;

const NOTES: Record<As, string> = {
  hr: "Dane fikcyjne, bez zapytań. Ogląda osoba z uprawnieniami Kadry i Płace.",
  manager: "Dane fikcyjne, bez zapytań. Ogląda przełożona: kartoteka i premie, stawek serwer nie przysyła (D2).",
  colleague: "Dane fikcyjne, bez zapytań. Ogląda osoba z zespołu: tylko wizytówka, sekcje modułów schowane.",
};

const { ola, paulina, marta, ewa } = HR_CAST;

function payroll(as: Exclude<As, "colleague">): PersonPayroll {
  const bonuses = closingBonuses(payrollScene()).filter((row) => row.recipient_user_id === ola.id);
  if (as === "manager") {
    return { user_id: ola.id, scope: "team", can_edit_rates: false, can_add_bonus: true, bonuses };
  }
  return {
    user_id: ola.id,
    scope: "full",
    can_edit_rates: true,
    can_add_bonus: true,
    bonuses,
    current_rate: OLA_RATES[0],
    rates: OLA_RATES,
  };
}

function prepare(params: URLSearchParams) {
  const as = pickState(params.get("as"), AS, "hr");
  const form = pickState(params.get("form"), FORMS, "b2b");
  const viewer =
    as === "hr"
      ? { ...paulina, grants: ["people_admin" as const, "payroll" as const] }
      : as === "manager"
        ? marta
        : ewa;
  const config: HrConfig =
    as === "hr"
      ? hrConfig({ people_admin: true, payroll: true })
      : as === "manager"
        ? hrConfig({ is_manager: true, direct_reports: MARTA_REPORTS.size })
        : hrConfig();
  const client = harnessQueryClient();
  client.setQueryData(HR_CONFIG_QUERY_KEY, config);
  client.setQueryData(HR_PEOPLE_KEYS.people, harnessDirectory());
  client.setQueryData(HR_PEOPLE_KEYS.person(ola.id), as === "colleague" ? personCard(ola) : olaFull(form));
  if (as === "colleague") {
    seedHttpError(client, LIFECYCLE_KEYS.summary(ola.id), 403, "Brak dostępu do tej sprawy.");
    seedHttpError(client, payrollKeys.person(ola.id), 404, "Nie ma takiej osoby w Płacach.");
  } else {
    client.setQueryData(LIFECYCLE_KEYS.summary(ola.id), { case: null, can_manage: as === "hr" });
    client.setQueryData(payrollKeys.person(ola.id), payroll(as));
  }
  // Panel sprzętu montuje się tylko dla Kadr, recepcji i admina.
  if (as === "hr") client.setQueryData(equipmentKeys.person(ola.id), OLA_EQUIPMENT);
  return { user: viewer, client, value: { as, config, form } };
}

export default function HrPersonPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { as, config, form } = ready.value;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Ludzie → Kartoteka osoby"
      note={NOTES[as]}
      states={STATES}
      current={as === "hr" && form !== "b2b" ? `hr-${form}` : as}
      param="as"
    >
      <PersonProfile userId={ola.id} config={config} />
    </HrHarnessShell>
  );
}
