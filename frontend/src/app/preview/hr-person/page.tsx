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
 * - `hr-only` — Kadry bez Płac (19.10.2026): kartoteka bez formy umowy; w „Edytuj
 *   kartotekę” forma „Bez zmian (forma ukryta)” — można ją zmienić bez podglądu;
 * - `finance` — Finanse (Płace bez Kadr): forma widoczna, „Zmień formę” zamiast
 *   „Edytuj kartotekę”;
 * - `account` — kartoteka założona z konta: forma i przełożony „do uzupełnienia”
 *   (ogląda Kadry i Płace).
 * Forma Oli (`?form=`, etap 2, D6–D9): `b2b` (domyślnie, płatne dni przerwy
 * z umowy), `zlecenie` (uczeń/student — składki od 01.07.2027, bez puli),
 * `uop` (staż do urlopu 12 lat, zaświadczenie ZUS, podpowiedź wymiaru 26 dni).
 * Okna „Edytuj kartotekę”, „Zmień pulę”, „Nowa stawka od…” i „Nowa premia”
 * otwierają się bez zapytań; zapisy blokuje harness.
 *
 * Makieta 19.10.2026: wizytówka z rzędem faktów (staż, forma, stawka — tylko
 * Płace, dni przerwy, premie, sprzęt), zakładki Przegląd · Nieobecności i godziny ·
 * Płace i premie · Dokumenty · Umowy · Sprzęt · Historia, pierścień dni
 * przerwy (`leave_balance`), oś „Ostatnio”, puste sekcje jako jedna linia
 * z akcją i „Rozpocznij odejście” w menu ⋯. `#place` otwiera „Płace i premie”.
 * Od 22.10.2026 zakładka „Nieobecności i godziny” (`#czas`) pokazuje też
 * nieobecności roku i raporty godzin osoby (`olaHistory`).
 */

import { PersonProfile } from "@/components/hr/people/PersonProfile";
import { hrKeys, isFullPerson, type EmploymentType, type HrConfig } from "@/lib/api/hr";
import { equipmentKeys } from "@/lib/api/equipment";
import { payrollKeys, type PersonPayroll } from "@/lib/api/hr-payroll";
import { lifecycleKeys } from "@/lib/api/hr-lifecycle";
import { agreementKeys } from "@/lib/api/hr-agreements";
import { documentKeys } from "@/lib/api/hr-documents";
import { personHistoryKey } from "@/lib/api/hr-person-history";
import { leaveKeys } from "@/lib/api/hr-leave";

import { HR_CAST, hrConfig } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";
import { MARTA_REPORTS, closingBonuses, payrollScene } from "../hr-payroll/fixtures";
import { olaAgreements } from "../hr-agreements/fixtures";
import {
  OLA_EQUIPMENT,
  OLA_RATES,
  harnessDirectory,
  harnessLeaveYear,
  olaFromAccount,
  olaFull,
  olaHistory,
  olaWithoutForm,
  personCard,
  seedHttpError,
} from "./fixtures";

const AS = ["hr", "manager", "colleague", "hr-only", "finance", "account"] as const;
type As = (typeof AS)[number];
const FORMS = ["b2b", "zlecenie", "uop"] as const satisfies readonly EmploymentType[];

const STATES = [
  { key: "hr", label: "Kadry i Płace" },
  { key: "hr-zlecenie", label: "Zlecenie: student", href: "?as=hr&form=zlecenie" },
  { key: "hr-uop", label: "UoP: staż do urlopu", href: "?as=hr&form=uop" },
  { key: "manager", label: "Przełożona (bez stawek)" },
  { key: "colleague", label: "Kolega z zespołu (wizytówka)" },
  { key: "hr-only", label: "Kadry bez Płac (bez formy)" },
  { key: "finance", label: "Finanse (Zmień formę)" },
  { key: "account", label: "Z konta: do uzupełnienia" },
] as const;

const NOTES: Record<As, string> = {
  hr: "Dane fikcyjne, bez zapytań. Ogląda osoba z uprawnieniami Kadry i Płace.",
  manager: "Dane fikcyjne, bez zapytań. Ogląda przełożona: kartoteka i premie, stawek serwer nie przysyła (D2).",
  colleague: "Dane fikcyjne, bez zapytań. Ogląda osoba z zespołu: tylko wizytówka, sekcje modułów schowane.",
  "hr-only":
    "Dane fikcyjne, bez zapytań. Ogląda osoba z Kadrami bez Płac: kartoteka bez formy umowy (19.10.2026).",
  finance:
    "Dane fikcyjne, bez zapytań. Ogląda osoba z Płacami bez Kadr: forma widoczna, „Zmień formę”.",
  account:
    "Dane fikcyjne, bez zapytań. Kartoteka założona z konta NEXUSA: forma i przełożony do uzupełnienia.",
};

const { ola, paulina, marta, ewa, piotr } = HR_CAST;

function payroll(as: Exclude<As, "colleague" | "hr-only">): PersonPayroll {
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
    as === "hr" || as === "account"
      ? { ...paulina, grants: ["people_admin" as const, "payroll" as const] }
      : as === "hr-only"
        ? { ...paulina, grants: ["people_admin" as const] }
        : as === "finance"
          ? { ...piotr, grants: ["payroll" as const] }
          : as === "manager"
            ? marta
            : ewa;
  const config: HrConfig =
    as === "hr" || as === "account"
      ? hrConfig({ people_admin: true, payroll: true })
      : as === "hr-only"
        ? hrConfig({ people_admin: true })
        : as === "finance"
          ? hrConfig({ payroll: true, has_profile: false })
          : as === "manager"
            ? hrConfig({ is_manager: true, direct_reports: MARTA_REPORTS.size })
            : hrConfig();
  const shown =
    as === "colleague"
      ? personCard(ola)
      : as === "hr-only"
        ? olaWithoutForm()
        : as === "account"
          ? olaFromAccount()
          : olaFull(form);
  // Saldo do pierścienia (B2B i UoP z pulą 26 + 2; zlecenie bez puli).
  const withRing =
    isFullPerson(shown) && shown.employment_type !== "zlecenie" && as !== "account"
      ? {
          ...shown,
          leave_balance: {
            year: harnessLeaveYear(),
            has_paid_pool: true,
            entitlement_days: "26.0",
            carried_over_days: "2.0",
            used_days: "16.5",
            planned_days: "3.0",
            remaining_days: "11.5",
          },
        }
      : isFullPerson(shown)
        ? { ...shown, leave_balance: null }
        : shown;
  const client = harnessQueryClient();
  client.setQueryData(hrKeys.config, config);
  client.setQueryData(hrKeys.people, harnessDirectory());
  client.setQueryData(hrKeys.person(ola.id), withRing);
  // E-teczka i umowy (etap 5) — puste, ten harness pokazuje kartotekę.
  client.setQueryData(documentKeys.person(ola.id), {
    user_id: ola.id,
    can_manage: as === "hr" || as === "hr-only" || as === "account",
    documents: [],
    protocols: [],
  });
  const agreements = olaAgreements();
  client.setQueryData(agreementKeys.person(ola.id), {
    ...agreements,
    person: { ...agreements.person, user_id: ola.id },
    agreements: [],
  });
  if (as === "colleague") {
    seedHttpError(client, lifecycleKeys.summary(ola.id), 403, "Brak dostępu do tej sprawy.");
    seedHttpError(client, payrollKeys.person(ola.id), 404, "Nie ma takiej osoby w Płacach.");
  } else {
    client.setQueryData(lifecycleKeys.summary(ola.id), {
      case: null,
      can_manage: as === "hr" || as === "hr-only" || as === "account",
    });
    if (as === "hr-only") {
      // Kadry bez Płac: sekcji „Płace” serwer odmawia — chowa się.
      seedHttpError(client, payrollKeys.person(ola.id), 403, "Płace widzą Finanse.");
    } else {
      client.setQueryData(payrollKeys.person(ola.id), payroll(as));
    }
  }
  // „Nieobecności i godziny” — tylko pełna kartoteka pyta serwer. Finanse spoza
  // kręgu D6 bez rodzaju, Kadry bez Płac bez słów formy.
  if (as !== "colleague") {
    client.setQueryData(
      personHistoryKey(ola.id, harnessLeaveYear()),
      olaHistory(form, harnessLeaveYear(), {
        typeVisible: as !== "finance",
        formVisible: as !== "hr-only",
      }),
    );
  }
  // „Dodaj za tę osobę”: lista osób z Akceptacji. Za B2B i zlecenie wpisują
  // tylko Kadry (D5), przełożony tylko za umowę o pracę.
  if (as === "hr" || as === "hr-only" || as === "account" || as === "manager") {
    client.setQueryData(leaveKeys.people, [
      {
        user_id: ola.id,
        name: ola.name,
        employment_type: form,
        department: "Rekrutacja IT",
        can_enter: as !== "manager" || form === "uop",
      },
    ]);
  }
  // Panel sprzętu montuje się tylko dla Kadr, recepcji i admina.
  if (as === "hr" || as === "hr-only" || as === "account") {
    client.setQueryData(equipmentKeys.person(ola.id), OLA_EQUIPMENT);
  }
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
