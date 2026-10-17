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
 *   i „Rozpocznij”.
 * Zapisy („Zapisz szkic”, „Rozpocznij”) blokuje harness.
 */

import { OnboardingCaseView } from "@/components/hr/lifecycle/OnboardingCaseView";
import { OnboardingWizard } from "@/components/hr/lifecycle/OnboardingWizard";
import type { HrConfig } from "@/lib/api/hr";

import { HR_CAST, HR_CONFIG_QUERY_KEY, hrConfig } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";
import { HR_PEOPLE_KEYS, LIFECYCLE_KEYS, harnessDirectory } from "../hr-person/fixtures";
import {
  ACCOUNTS_WITHOUT_PROFILE,
  ONBOARDING_CASE_ID,
  ONBOARDING_DRAFT_ID,
  ONBOARDING_TEMPLATES,
  onboardingCase,
  onboardingScene,
  previewSeeds,
} from "./fixtures";

const STATE_KEYS = ["wizard", "case", "draft"] as const;

const STATES = [
  { key: "wizard", label: "Kreator (krok 1)" },
  { key: "case", label: "Sprawa w toku" },
  { key: "draft", label: "Szkic bez konta" },
] as const;

function prepare(params: URLSearchParams) {
  const state = pickState(params.get("state"), STATE_KEYS, "wizard");
  const scene = onboardingScene();
  const config: HrConfig = hrConfig({ people_admin: true });
  const client = harnessQueryClient();
  client.setQueryData(HR_CONFIG_QUERY_KEY, config);
  client.setQueryData(HR_PEOPLE_KEYS.people, harnessDirectory());
  client.setQueryData(HR_PEOPLE_KEYS.withoutProfile, ACCOUNTS_WITHOUT_PROFILE);
  client.setQueryData(LIFECYCLE_KEYS.templates("onboarding"), ONBOARDING_TEMPLATES);
  for (const seed of previewSeeds(scene.start)) client.setQueryData(seed.key, seed.data);
  client.setQueryData(LIFECYCLE_KEYS.case(ONBOARDING_CASE_ID), onboardingCase(scene, "active"));
  client.setQueryData(LIFECYCLE_KEYS.case(ONBOARDING_DRAFT_ID), onboardingCase(scene, "draft"));
  return {
    user: { ...HR_CAST.paulina, grants: ["people_admin" as const] },
    client,
    value: { state, config, start: scene.start },
  };
}

export default function HrOnboardingPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { state, config, start } = ready.value;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Ludzie → Wejście nowej osoby"
      note={`Dane fikcyjne, bez zapytań. Prowadzą Kadry. Podgląd zadań zasiany dla startu ${start}.`}
      states={STATES}
      current={state}
    >
      {state === "wizard" ? (
        <OnboardingWizard config={config} />
      ) : (
        <OnboardingCaseView caseId={state === "case" ? ONBOARDING_CASE_ID : ONBOARDING_DRAFT_ID} />
      )}
    </HrHarnessShell>
  );
}
