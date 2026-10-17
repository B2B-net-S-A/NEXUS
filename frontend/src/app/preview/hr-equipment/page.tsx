"use client";

/**
 * Harness „Firma → Sprzęt: ewidencja” (makieta 12 raportu „Ludzie w NEXUSIE”).
 *
 * Prawdziwy `EquipmentScreen` (ta sama strona co `/equipment`, bez
 * `HrConfigGate`) na zasianym cache, ZERO zapytań (`hr-harness.tsx`). Ogląda
 * recepcja (Zofia Recepcyjna) z uprawnieniem „Sprzęt”. Rejestr to chwila trzy
 * dni po wydaniu zestawu kontraktorce: liczniki z makiety (11 wolnych laptopów,
 * 14 telefonów, 8 monitorów, 3 protokoły czekają na podpis, 31 wierszy importu
 * do wyjaśnienia), wydane i podpisane, wolne, w serwisie, karta SIM w telefonie,
 * karta dostępu i „Do zrobienia” (przygotuj, czeka na podpis, zwroty, po terminie).
 *
 * Stany to zakładki ekranu (`?tab=`, czyta je sam `EquipmentScreen`):
 * `items` (domyślnie), `tasks`, `protocols`, `prices`, `import`, `intune`
 * (odczyt z Intune jeszcze niepodłączony). Zasiane są też filtry rejestru
 * (jeden naraz), szczegół każdej pozycji, szczegół każdego protokołu, kreator
 * wydania i przyjęcia zwrotu z „Do zrobienia”, decyzje partii importu
 * i zakładka „Akademia” — klik nie wysyła zapytania. Dane fikcyjne
 * (`./fixtures.ts`).
 */

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { EquipmentScreen, type EquipmentTab } from "@/components/equipment/EquipmentScreen";
import type { HrConfig } from "@/lib/api/hr";

import { HR_CAST, HR_CONFIG_QUERY_KEY, hrConfig } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
  type HrHarnessReady,
  type HrHarnessSetup,
} from "../hr-harness";
import { buildEquipmentData, seedEquipment } from "./fixtures";

const TABS: readonly EquipmentTab[] = [
  "items",
  "tasks",
  "protocols",
  "prices",
  "import",
  "intune",
  "academy",
];

const STATES = [
  { key: "items", label: "Ewidencja" },
  { key: "tasks", label: "Do zrobienia (6)" },
  { key: "protocols", label: "Protokoły" },
  { key: "prices", label: "Cennik" },
  { key: "import", label: "Import (31 do wyjaśnienia)" },
  { key: "intune", label: "Intune (niepodłączone)" },
] as const;

interface Value {
  config: HrConfig;
}

function prepare(): HrHarnessSetup<Value> {
  const config = hrConfig({ equipment: true });
  const client = harnessQueryClient();
  client.setQueryData(HR_CONFIG_QUERY_KEY, config);
  seedEquipment(client, buildEquipmentData("after"));
  return { user: { ...HR_CAST.zofia, grants: ["equipment"] }, client, value: { config } };
}

/** Pod `<Suspense>`: `EquipmentScreen` i pasek stanów czytają `?tab=` przez `useSearchParams`. */
function EquipmentHarness({ ready }: { ready: HrHarnessReady<Value> }) {
  const params = useSearchParams();
  const tab = pickState(params.get("tab"), TABS, "items");
  return (
    <HrHarnessShell
      client={ready.client}
      title="Firma → Sprzęt"
      note="Recepcja z uprawnieniem „Sprzęt”. Dane fikcyjne, bez zapytań; numery seryjne, IMEI i protokoły zmyślone."
      states={STATES}
      current={tab}
      param="tab"
    >
      <EquipmentScreen config={ready.value.config} />
    </HrHarnessShell>
  );
}

export default function HrEquipmentPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  return (
    <Suspense fallback={<HrHarnessLoading />}>
      <EquipmentHarness ready={ready} />
    </Suspense>
  );
}
