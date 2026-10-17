"use client";

/**
 * Harness „Ludzie → osoba → Odejście” (makieta 8 raportu „Ludzie w NEXUSIE”).
 *
 * Prawdziwy `OffboardingScreen` (strona `/people/[userId]/offboarding`) na
 * zasianym cache, ZERO zapytań (`hr-harness.tsx`). Prowadzą Kadry; odchodzi
 * rekruter Tomasz, ostatni dzień w przyszłym miesiącu.
 *
 * Stany (`?state=`):
 * - `case` (domyślnie) — odejście rozpoczęte: „Co Tomasz ma w NEXUSIE” z
 *   przejmującymi (rekrutacje → Ola, „Moi ludzie” → Ewa), „Kiedy co się
 *   stanie” (przekazanie o 18:00, wyłączenie konta dzień później), zadania 2/6;
 * - `draft` — szkic: zadania czekają na „Rozpocznij”, przejmującą jest
 *   przełożona;
 * - `form` — bez sprawy: formularz „Ostatni dzień pracy”, przełożony, powód,
 *   lista zadań.
 * Listy „Przekaż do” są zasiane; „Zmień ostatni dzień” i „Cofnij odejście”
 * otwierają okna bez zapytań, zapisy blokuje harness.
 */

import { OffboardingScreen } from "@/components/hr/lifecycle/OffboardingScreen";
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
  OFFBOARDING_CASE_ID,
  OFFBOARDING_TEMPLATES,
  TRANSFER_KINDS,
  offboardingCase,
  offboardingScene,
  receiversFor,
  tomaszProfile,
} from "./fixtures";

const STATE_KEYS = ["case", "draft", "form"] as const;

const STATES = [
  { key: "case", label: "Odejście w toku (2/6 zadań)" },
  { key: "draft", label: "Szkic" },
  { key: "form", label: "Bez sprawy (formularz)" },
] as const;

const { tomasz, paulina } = HR_CAST;

function prepare(params: URLSearchParams) {
  const state = pickState(params.get("state"), STATE_KEYS, "case");
  const scene = offboardingScene();
  const config: HrConfig = hrConfig({ people_admin: true });
  const client = harnessQueryClient();
  client.setQueryData(hrKeys.config, config);
  client.setQueryData(hrKeys.people, harnessDirectory());
  if (state === "form") {
    client.setQueryData(hrKeys.person(tomasz.id), tomaszProfile(null));
    client.setQueryData(lifecycleKeys.summary(tomasz.id), { case: null, can_manage: true });
    client.setQueryData(lifecycleKeys.templates("offboarding"), OFFBOARDING_TEMPLATES);
  } else {
    const item = offboardingCase(scene, state === "case" ? "active" : "draft");
    client.setQueryData(hrKeys.person(tomasz.id), tomaszProfile(scene));
    client.setQueryData(lifecycleKeys.summary(tomasz.id), {
      case: {
        id: item.id,
        kind: item.kind,
        status: item.status,
        start_date: item.start_date,
        last_working_day: item.last_working_day,
        deactivate_on: item.deactivate_on,
        handover_executed_at: item.handover_executed_at,
        account_closed_at: item.account_closed_at,
        account_close_result: item.account_close_result,
        progress: item.progress,
        link: `/people/${tomasz.id}/offboarding`,
      },
      can_manage: true,
    });
    client.setQueryData(lifecycleKeys.case(OFFBOARDING_CASE_ID), item);
    for (const kind of TRANSFER_KINDS) {
      client.setQueryData(lifecycleKeys.receivers(OFFBOARDING_CASE_ID, kind), receiversFor(kind));
    }
  }
  return {
    user: { ...paulina, grants: ["people_admin" as const] },
    client,
    value: { state, config },
  };
}

export default function HrOffboardingPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { state, config } = ready.value;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Ludzie → Odejście"
      note="Dane fikcyjne, bez zapytań. Prowadzą Kadry; ostatni dzień pracy w przyszłym miesiącu."
      states={STATES}
      current={state}
    >
      <OffboardingScreen userId={tomasz.id} config={config} />
    </HrHarnessShell>
  );
}
