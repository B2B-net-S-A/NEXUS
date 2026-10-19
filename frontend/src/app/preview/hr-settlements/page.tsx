"use client";

/**
 * Harness „Rozliczenia zespołu” (etap 4, makiety M1–M4 i M7).
 *
 * Prawdziwe komponenty na zasianym cache, ZERO zapytań (`hr-harness.tsx`).
 * Miesiąc to poprzedni miesiąc przeglądarki.
 *
 * Stany (`?state=`):
 * - `b2b` (domyślnie) — „Mój czas → Rozliczenie” Oli na B2B: kroki od raportu
 *   do zapłaty, „Do faktury” z pozycjami i „Kopiuj pozycje”, faktura z KSeF,
 *   poprzedni miesiąc opłacony (M1);
 * - `mandate` — Ewa na zleceniu: rozliczenie z potwierdzenia godzin, PDF (M2);
 * - `queue` — Płace: jedna kolejka trzech form, rozbieżność na górze (M3);
 * - `mismatch` — porównanie rozbieżności z decyzjami Płac (M4);
 * - `billing` — Kadry: dane do rozliczeń z białą listą (M7).
 * Zapisy i pobrania blokuje harness.
 */

import { MySettlementTab } from "@/components/hr/me/MySettlementTab";
import { SettlementsQueue } from "@/components/hr/payroll/SettlementsQueue";
import { BillingDetailsSection } from "@/components/hr/people/BillingDetailsSection";
import { hrKeys, type HrConfig } from "@/lib/api/hr";
import { settlementKeys } from "@/lib/api/hr-settlements";

import { HR_CAST, hrConfig } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
  type HarnessUser,
} from "../hr-harness";
import {
  ewaSettlements,
  mismatchDetail,
  olaBilling,
  olaSettlements,
  queue,
  settlementScene,
} from "./fixtures";

const STATE_KEYS = ["b2b", "mandate", "queue", "mismatch", "billing"] as const;
type State = (typeof STATE_KEYS)[number];

const STATES = [
  { key: "b2b", label: "B2B: do faktury" },
  { key: "mandate", label: "Zlecenie: rozliczenie" },
  { key: "queue", label: "Płace: kolejka" },
  { key: "mismatch", label: "Płace: rozbieżność", href: "?state=mismatch&settlement=5003" },
  { key: "billing", label: "Kadry: dane do rozliczeń" },
] as const;

const NOTES: Record<State, string> = {
  b2b: "Dane fikcyjne, bez zapytań. Ogląda Ola na B2B — faktura zgodna, czeka na termin.",
  mandate: "Dane fikcyjne, bez zapytań. Ogląda Ewa na zleceniu — rozliczenie z potwierdzenia godzin.",
  queue: "Dane fikcyjne, bez zapytań. Ogląda Finanse z uprawnieniem Płace.",
  mismatch: "Dane fikcyjne, bez zapytań. Faktura wyższa o 120,00 zł — decyzja Płac z drugą osobą.",
  billing: "Dane fikcyjne, bez zapytań. Ogląda Kadry; przełożony i zespół tej sekcji nie widzą.",
};

function settlementsConfig(me: Partial<HrConfig["me"]> = {}): HrConfig {
  const config = hrConfig(me);
  return {
    ...config,
    modules: { ...config.modules, settlements: true },
    open_modules: { ...config.open_modules, settlements: true },
  };
}

function prepare(params: URLSearchParams) {
  const state = pickState(params.get("state"), STATE_KEYS, "b2b");
  const scene = settlementScene();
  const client = harnessQueryClient();
  let user: HarnessUser = HR_CAST.ola;
  let config = settlementsConfig();
  if (state === "b2b" || state === "mandate") {
    const mine = state === "b2b" ? olaSettlements(scene) : ewaSettlements(scene);
    if (state === "mandate") user = HR_CAST.ewa;
    client.setQueryData(settlementKeys.me(scene.currentYear), mine);
    // Zakładka pyta też o poprzedni rok (przełom roku) — harness bez żądań.
    client.setQueryData(settlementKeys.me(scene.currentYear - 1), {
      ...mine,
      year: scene.currentYear - 1,
      months: [],
    });
  } else if (state === "queue" || state === "mismatch") {
    user = { ...HR_CAST.piotr, grants: ["payroll"] };
    config = settlementsConfig({ payroll: true });
    client.setQueryData(settlementKeys.month(scene.year, scene.month), queue(scene));
    client.setQueryData(settlementKeys.detail(5003), mismatchDetail(scene));
  } else {
    user = { ...HR_CAST.paulina, grants: ["people_admin", "payroll"] };
    config = settlementsConfig({ people_admin: true, payroll: true });
    client.setQueryData(settlementKeys.billing(HR_CAST.ola.id), olaBilling(scene));
  }
  client.setQueryData(hrKeys.config, config);
  return { user, client, value: { state, scene } };
}

export default function HrSettlementsPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { state, scene } = ready.value;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Rozliczenia zespołu"
      note={NOTES[state]}
      states={STATES}
      current={state}
    >
      {state === "b2b" || state === "mandate" ? (
        <MySettlementTab />
      ) : state === "billing" ? (
        <BillingDetailsSection userId={HR_CAST.ola.id} enabled />
      ) : (
        <SettlementsQueue year={scene.year} month={scene.month} />
      )}
    </HrHarnessShell>
  );
}
