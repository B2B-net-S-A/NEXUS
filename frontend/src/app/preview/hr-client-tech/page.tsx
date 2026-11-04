"use client";

/**
 * Harness „Technologie klienta” (makieta 10 raportu „Ludzie w NEXUSIE”).
 *
 * Od 22.10.2026 to widok „Mapa” zakładki „Ludzie i technologie” profilu
 * klienta (`/clients/[id]?tab=ludzie&view=mapa`; dawne `?tab=technologie`
 * prowadzi tu). Harness nie montuje całej strony klienta — pokazuje prosty
 * nagłówek klienta i pod nim prawdziwy `ClientPeopleTechTab` w widoku „Mapa”
 * (w środku dawny `ClientTechnologiesTab`) na zasianym cache, ZERO zapytań
 * (`hr-harness.tsx`). Ogląda Delivery Lead klienta (może dodać notatkę
 * o stacku i zmienić domyślnego opiekuna). Przełącznik widoków działa —
 * działy i drzewo mają osobny harness `/preview/hr-client-people`.
 *
 * Stan „links”: nad mapą „Karty z Compassa do połączenia” (import 18.10.2026)
 * — karta z dwiema propozycjami i karta bez kontraktu z tym nazwiskiem.
 *
 * Stan „map”: mapa cieplna technologia × dział z czterech źródeł (T rozmowy,
 * R rekrutacje, K nasi konsultanci, N notatki; makieta 19.10.2026) — 7
 * technologii, cztery działy (jeden bez źródła), obramowane komórki
 * z otwartą rekrutacją, kolumna „bez działu”, luki do dopytania z akcją,
 * „Klient zatrudnia”, „Do przepięcia” = 2, trzy otwarte rekrutacje z działem,
 * dostawcy i domyślny opiekun. „Dodaj notatkę o stacku” otwiera okno bez
 * zapytań, lista opiekunów jest zasiana.
 *
 * Stan „many”: jak duży bank na prodzie 20.10.2026 — 67 działów ze „Struktury
 * u klienta” bez żadnego źródła, cały sygnał w „bez działu”. Puste działy
 * są schowane („Pokaż wszystkie działy (67)”), „bez działu” stoi pierwsze.
 */

import { useState } from "react";

import { ClientPeopleTechTab } from "@/components/care/client/ClientPeopleTechTab";
import type { PeopleView } from "@/components/care/client/people-tech-format";
import { careKeys, type ClientTechMap } from "@/lib/api/care";
import { clientPeopleKeys } from "@/lib/api/client-people";
import { warsawToday } from "@/lib/warsaw-date";
import { hrKeys } from "@/lib/api/hr";

import { HR_CAST, hrConfig } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";
import { seedStructure } from "../hr-client-structure/fixtures";
import { clientOrgWithHealth } from "../hr-client-people/fixtures";
import { CARE_OWNERS, MAP_CLIENT, clientTechMap, unlinkedCards } from "./fixtures";

const STATES = [
  { key: "map", label: "Mapa (Delivery Lead klienta)" },
  { key: "links", label: "Karty z Compassa do połączenia" },
  { key: "many", label: "67 pustych działów" },
] as const;
type HarnessState = (typeof STATES)[number]["key"];

/** 67 działów bez źródeł; wiersze mapy mają sygnał tylko w „bez działu”. */
function manyEmptyDepartments(map: ClientTechMap): ClientTechMap {
  const departments = Array.from({ length: 67 }, (_, i) => ({
    ...map.departments[0],
    area: { id: 7000 + i, name: `Dział ${String(i + 1).padStart(2, "0")} — zespół przykładowy` },
    technologies: [],
    technologies_total: 0,
    managers: [],
    consultants: 0,
    has_fresh_source: true,
    base: { skills: [], count: null },
  }));
  const rows = (map.heatmap?.rows ?? []).map((row) => ({
    ...row,
    cells: departments.map(() => null),
    unassigned: row.unassigned ?? row.cells.find(Boolean) ?? null,
  }));
  return { ...map, departments, heatmap: { rows, rows_total: rows.length } };
}

function prepare(params: URLSearchParams) {
  const state: HarnessState = pickState(params.get("state"), ["map", "links", "many"] as const, "map");
  const today = warsawToday();
  const map = state === "many" ? manyEmptyDepartments(clientTechMap(today)) : clientTechMap(today);
  const client = harnessQueryClient();
  client.setQueryData(hrKeys.config, hrConfig());
  client.setQueryData(careKeys.clientMap(MAP_CLIENT.id), map);
  // „map”: wszystkie karty połączone — sekcji „do połączenia” nie ma.
  client.setQueryData(
    careKeys.clientUnlinkedCards(MAP_CLIENT.id),
    state === "links" ? unlinkedCards(today) : { items: [], contracts: [], can_link: true },
  );
  client.setQueryData(careKeys.owners, CARE_OWNERS);
  // Nagłówek zakładki i pasek „Do zatwierdzenia” czytają drzewo i propozycje.
  client.setQueryData(clientPeopleKeys.org(MAP_CLIENT.id), clientOrgWithHealth(today));
  seedStructure(client, today);
  return {
    user: HR_CAST.kamil,
    client,
    value: { consultants: map.consultants_count, openJobs: map.open_jobs_count, state },
  };
}

/** Uproszczony nagłówek profilu klienta — tylko kontekst dla zakładki. */
function ClientHeader({ consultants, openJobs }: { consultants: number; openJobs: number }) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2.5 sm:px-5">
        <span className="text-xs text-muted-foreground">Klienci</span>
        <span aria-hidden="true" className="text-xs text-muted-foreground">
          /
        </span>
        <h2 className="font-display text-lg font-semibold text-foreground">{MAP_CLIENT.name}</h2>
        <span className="text-xs text-muted-foreground">
          {consultants} konsultantów u klienta · {openJobs} otwarte rekrutacje
        </span>
      </div>
      <div className="border-t border-border px-3 text-[13px] sm:px-5">
        <span className="inline-block border-b-2 border-primary px-3 py-2 font-semibold text-foreground">
          Ludzie i technologie
        </span>
      </div>
    </div>
  );
}

function MapView() {
  const [view, setView] = useState<PeopleView>("mapa");
  return <ClientPeopleTechTab clientId={MAP_CLIENT.id} view={view} onViewChange={setView} />;
}

export default function HrClientTechPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Technologie klienta"
      note="Dane fikcyjne, bez zapytań. Ogląda Delivery Lead klienta; liczby źródeł to karty, rekrutacje, konsultanci i notatki z technologią."
      states={STATES}
      current={ready.value.state}
    >
      <div className="space-y-4">
        <ClientHeader consultants={ready.value.consultants} openJobs={ready.value.openJobs} />
        <MapView />
      </div>
    </HrHarnessShell>
  );
}
