"use client";

/**
 * Harness „Sprzęt → Wydaj sprzęt · pozycje i protokół” (makieta 13 raportu
 * „Ludzie w NEXUSIE”).
 *
 * Prawdziwy `IssueWizard` (i `ReturnWizard`) nad prawdziwym `EquipmentScreen`,
 * na zasianym cache, ZERO zapytań (`hr-harness.tsx`). Ogląda recepcja
 * z uprawnieniem „Sprzęt”. Rejestr to chwila przed wydaniem: zestaw
 * kontraktorki (laptop 221, telefon T-102, SIM w telefonie, słuchawki J-044,
 * karta dostępu K-1611) leży jeszcze na stanie, razem 3 903,73 zł.
 *
 * Stan `kit` otwiera kreator tak jak „Wydaj” z zadania „Przygotuj zestaw
 * kontraktora” — z osobą z góry i podpowiedzianym „Zestawem kontraktora”, od
 * razu na kroku 2 („Pozycje”): gotowe zestawy, zakładki kategorii z liczbą
 * wolnych, lista po modelu z wyborem sztuki i żywy podgląd protokołu; krok 3
 * („Protokół i podpis”) to podgląd protokołu (test harnessu przeklikuje całą drogę).
 *
 * Stany (`?state=`):
 * - `kit` (domyślnie) — kontraktorka Anna Kontraktorska (Ubezpieczenia
 *   Fikcyjne), krok 2 → 3;
 * - `model` — „Wydaj” przy modelu w „Ewidencji” (pierwsza wolna Latitude 148
 *   już w szkicu), krok 1 — wybór osoby;
 * - `person` — „Wydaj sprzęt” z nagłówka: krok 1, wyszukiwarka osób
 *   (zasiane frazy „Anna…”, „Kacper…”, „Michał…”, „Tomasz…”);
 * - `return` — „Przyjmij zwrot” osoby odchodzącej (Tomasz Podglądowy, 4 pozycje).
 * Zamknięcie okna zostawia przycisk „Otwórz ponownie”. Dane fikcyjne
 * (`../hr-equipment/fixtures.ts`).
 */

import { Suspense, useState } from "react";

import { EquipmentScreen } from "@/components/equipment/EquipmentScreen";
import { IssueWizard } from "@/components/equipment/IssueWizard";
import { ReturnWizard } from "@/components/equipment/ReturnWizard";
import { Button } from "@/components/ui/button";
import type { EquipmentHolder, EquipmentItem } from "@/lib/api/equipment";
import { hrKeys, type HrConfig } from "@/lib/api/hr";

import { HR_CAST, hrConfig } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
  type HrHarnessSetup,
} from "../hr-harness";
import { buildEquipmentData, seedEquipment } from "../hr-equipment/fixtures";

const STATE_KEYS = ["kit", "model", "person", "return"] as const;
type State = (typeof STATE_KEYS)[number];

const STATES = [
  { key: "kit", label: "Zestaw kontraktora (pozycje → protokół)" },
  { key: "model", label: "„Wydaj” z modelu w Ewidencji" },
  { key: "person", label: "Wybór osoby (krok 1)" },
  { key: "return", label: "Przyjęcie zwrotu (odejście)" },
] as const;

const NOTES: Record<State, string> = {
  kit: "Kontraktorka z kontraktu, zestaw kontraktora z listy wolnego sprzętu. Dane fikcyjne, bez zapytań.",
  model: "Pierwsza wolna sztuka modelu już w szkicu protokołu; wybierz osobę. Dane fikcyjne, bez zapytań.",
  person: "Wpisz „Anna”, wybierz kontraktorkę i przejdź dalej. Dane fikcyjne, bez zapytań.",
  return: "Osoba odchodzi: cztery pozycje ze stanem przy zwrocie. Dane fikcyjne, bez zapytań.",
};

interface Value {
  state: State;
  config: HrConfig;
  contractor: EquipmentHolder;
  leaver: EquipmentHolder;
  firstLatitude: EquipmentItem;
}

function prepare(params: URLSearchParams): HrHarnessSetup<Value> {
  const state = pickState(params.get("state"), STATE_KEYS, "kit");
  const config = hrConfig({ equipment: true });
  const client = harnessQueryClient();
  client.setQueryData(hrKeys.config, config);
  const data = buildEquipmentData("before");
  seedEquipment(client, data);
  return {
    user: { ...HR_CAST.zofia, grants: ["equipment"] },
    client,
    value: {
      state,
      config,
      contractor: data.holders.anna,
      leaver: data.holders.tomasz,
      firstLatitude: data.items.find((item) => item.id === 148) as EquipmentItem,
    },
  };
}

/** Okno z makiety; po zamknięciu — przycisk, który otwiera je od nowa. */
function HarnessWizard({ value }: { value: Value }) {
  const [round, setRound] = useState(0);
  const [open, setOpen] = useState(true);
  const close = () => setOpen(false);

  if (!open) {
    return (
      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted-foreground">
        Okno zamknięte.
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            setRound((previous) => previous + 1);
            setOpen(true);
          }}
        >
          Otwórz ponownie
        </Button>
      </div>
    );
  }
  if (value.state === "return") {
    return <ReturnWizard key={round} presetHolder={value.leaver} onClose={close} />;
  }
  return (
    <IssueWizard
      key={round}
      presetHolder={value.state === "kit" ? value.contractor : null}
      presetItems={value.state === "model" ? [value.firstLatitude] : []}
      suggestedKit={value.state === "kit" ? "kontraktor" : null}
      onClose={close}
    />
  );
}

export default function HrEquipmentIssuePreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { value } = ready;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Sprzęt → Wydaj sprzęt"
      note={NOTES[value.state]}
      states={STATES}
      current={value.state}
    >
      <HarnessWizard value={value} />
      {/* Ekran pod oknem — `EquipmentScreen` czyta zakładkę z adresu. */}
      <Suspense fallback={null}>
        <EquipmentScreen config={value.config} />
      </Suspense>
    </HrHarnessShell>
  );
}
