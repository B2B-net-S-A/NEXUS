"use client";

/**
 * Harness „Ludzie → Nowa osoba” (makieta 14 raportu „Ludzie w NEXUSIE”).
 *
 * Prawdziwy `OnboardingWizard` (strona `/people/new`) i `OnboardingCaseView`
 * (strona `/people/new/[caseId]`) na zasianym cache, ZERO zapytań
 * (`hr-harness.tsx`). Prowadzą Kadry; wchodzi rekruter Kacper, start pierwszego
 * dnia roboczego przyszłego miesiąca.
 *
 * Stany (`?state=`):
 * - `wizard` (domyślnie) — kreator od kroku 1 „Osoba i konto” (kreator nie
 *   ma wejścia na krok z adresu). Zasiane: konta bez kartoteki, katalog
 *   przełożonych, listy zadań i podgląd zadań dla daty startu ze sceny
 *   (każda forma, dział pusty albo „Rekrutacja IT”) — przejście do kroku
 *   „Zadania” z tą datą nie wysyła zapytania;
 * - `case` — sprawa w toku: zatrudnienie, zadania recepcji, IT i przełożonej
 *   (1 z 8 zrobione), „Zakończ wejście”;
 * - `draft` — szkic osoby bez konta: informacja o koncie z adresem
 *   i „Rozpocznij”;
 * - `contract` (etap 3, M6) — zakładka „Wejście” kontraktu konsultanta
 *   oczami opiekunki: kroki, lista ze ścieżki, pakietu klienta i formy,
 *   „Z czego to powstało”, mail powitalny (przełącznik wyłączony);
 * - `paths` (etap 3, M4) — „Ścieżki wejścia i odejścia” oczami head back
 *   office: ścieżkę konsultanta zmienia, zespołu tylko ogląda.
 * Zapisy („Zapisz szkic”, „Rozpocznij”, odhaczenia, „Zapisz jako wersję”)
 * blokuje harness.
 */

import { LifecycleTemplatesCard } from "@/components/hr/lifecycle/LifecycleTemplatesCard";
import { OnboardingCaseView } from "@/components/hr/lifecycle/OnboardingCaseView";
import { OnboardingWizard } from "@/components/hr/lifecycle/OnboardingWizard";
import { ContractEntryTab } from "@/components/hr/onboarding/ContractEntryTab";
import { clientOnboardingKeys } from "@/lib/api/client-onboarding";
import { hrKeys, type HrConfig } from "@/lib/api/hr";
import { lifecycleKeys } from "@/lib/api/hr-lifecycle";

import { HR_CAST, hrConfig } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";
import { harnessDirectory } from "../hr-person/fixtures";
import {
  ACCOUNTS_WITHOUT_PROFILE,
  ONBOARDING_CASE_ID,
  ONBOARDING_DRAFT_ID,
  ONBOARDING_TEMPLATES,
  onboardingCase,
  onboardingScene,
  previewSeeds,
} from "./fixtures";
import {
  ENTRY_CONTRACT_ID,
  PATH_TEMPLATES,
  consultantEntry,
  welcomeMailOff,
} from "./consultant-fixtures";

const STATE_KEYS = ["wizard", "case", "draft", "contract", "paths"] as const;

const STATES = [
  { key: "wizard", label: "Kreator (krok 1)" },
  { key: "case", label: "Sprawa w toku" },
  { key: "draft", label: "Szkic bez konta" },
  { key: "contract", label: "Wejście konsultanta" },
  { key: "paths", label: "Ścieżki" },
] as const;

function prepare(params: URLSearchParams) {
  const state = pickState(params.get("state"), STATE_KEYS, "wizard");
  const scene = onboardingScene();
  const config: HrConfig = hrConfig({ people_admin: true });
  const client = harnessQueryClient();
  client.setQueryData(hrKeys.config, config);
  client.setQueryData(hrKeys.people, harnessDirectory());
  client.setQueryData(hrKeys.withoutProfile, ACCOUNTS_WITHOUT_PROFILE);
  client.setQueryData(lifecycleKeys.templates("onboarding"), ONBOARDING_TEMPLATES);
  for (const seed of previewSeeds(scene.start)) client.setQueryData(seed.key, seed.data);
  client.setQueryData(lifecycleKeys.case(ONBOARDING_CASE_ID), onboardingCase(scene, "active"));
  client.setQueryData(lifecycleKeys.case(ONBOARDING_DRAFT_ID), onboardingCase(scene, "draft"));
  client.setQueryData(lifecycleKeys.contractEntry(ENTRY_CONTRACT_ID), consultantEntry(scene));
  client.setQueryData(clientOnboardingKeys.welcome(ENTRY_CONTRACT_ID), welcomeMailOff(scene));
  client.setQueryData(lifecycleKeys.templates(null), PATH_TEMPLATES);
  const consultantSide = state === "contract" || state === "paths";
  return {
    user: consultantSide
      ? { ...HR_CAST.natalia }
      : { ...HR_CAST.paulina, grants: ["people_admin" as const] },
    client,
    value: { state, config, start: scene.start },
  };
}

function Screen({ state, config }: { state: (typeof STATE_KEYS)[number]; config: HrConfig }) {
  if (state === "wizard") return <OnboardingWizard config={config} />;
  if (state === "contract") return <ContractEntryTab contractId={ENTRY_CONTRACT_ID} />;
  if (state === "paths") return <LifecycleTemplatesCard />;
  return (
    <OnboardingCaseView caseId={state === "case" ? ONBOARDING_CASE_ID : ONBOARDING_DRAFT_ID} />
  );
}

export default function HrOnboardingPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { state, config, start } = ready.value;
  return (
    <HrHarnessShell
      client={ready.client}
      title={
        state === "contract"
          ? "Kontrakty → Wejście konsultanta"
          : state === "paths"
            ? "Ustawienia → Ścieżki wejścia i odejścia"
            : "Ludzie → Wejście nowej osoby"
      }
      note={`Dane fikcyjne, bez zapytań. ${
        state === "contract" || state === "paths"
          ? "Ogląda opiekunka i head back office."
          : "Prowadzą Kadry."
      } Start ${start}.`}
      states={STATES}
      current={state}
    >
      <Screen state={state} config={config} />
    </HrHarnessShell>
  );
}
