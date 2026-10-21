"use client";

/**
 * Harness „Ludzie i technologie” — zakładka klienta (`/clients/[id]?tab=ludzie`,
 * decyzja 5 z makiet 22.10.2026; zastępuje „Strukturę u klienta” i „Technologie”).
 *
 * Harness pokazuje prosty nagłówek klienta i pod nim prawdziwy
 * `ClientPeopleTechTab` na zasianym cache, ZERO zapytań (`hr-harness.tsx`).
 * Ogląda Delivery Lead klienta (krąg D11 — drzewo, opinie, propozycje).
 *
 * Stany:
 * - `dzialy` (domyślny) — karty działów: Płatności z otwartymi rekrutacjami
 *   (żółta ramka) i kropką „Ryzyko” przy konsultantce, Data z menedżerem
 *   i „Podlega pod”, Kredyty bez naszych; z prawej luki, ludzie poza działami,
 *   dostawcy, notatki o stacku i domyślny opiekun; nad widokami pasek
 *   „Do zatwierdzenia” z jedną propozycją automatu;
 * - `drzewo` — dawna „Struktura u klienta” (drzewo osób z panelem osoby);
 * - `zatwierdz` — pasek „Do zatwierdzenia” rozwinięty do pełnego panelu;
 * - `popyt` — okno „Rozmowa z menedżerem” z karty „Popyt do sprawdzenia”
 *   (sekcja „Czego potrzebuje dział?”, menedżer do wybrania);
 * - `finanse` — konto spoza kręgu D11: działy z mapy, bez drzewa i opinii.
 * Mapa technologii (widok „Mapa”) ma osobny harness `/preview/hr-client-tech`.
 * Zapisy odcina interceptor harnessu.
 */

import { useState } from "react";

import { ClientFeedbackDialog } from "@/components/care/ClientFeedbackDialog";
import { ClientPeopleTechTab } from "@/components/care/client/ClientPeopleTechTab";
import type { PeopleView } from "@/components/care/client/people-tech-format";
import { careKeys } from "@/lib/api/care";
import { clientPeopleKeys } from "@/lib/api/client-people";
import { hrKeys } from "@/lib/api/hr";
import { warsawToday } from "@/lib/warsaw-date";

import { HR_CAST, hrConfig } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";
import { seedStructure } from "../hr-client-structure/fixtures";
import { CARE_OWNERS } from "../hr-client-tech/fixtures";
import { ORG_CLIENT, clientOrgWithHealth, peopleTechMap } from "./fixtures";

const KNOWN = ["dzialy", "drzewo", "zatwierdz", "popyt", "finanse"] as const;
type HarnessState = (typeof KNOWN)[number];

const STATES = [
  { key: "dzialy", label: "Działy (Delivery Lead)" },
  { key: "drzewo", label: "Drzewo osób" },
  { key: "zatwierdz", label: "Do zatwierdzenia — wszystkie" },
  { key: "popyt", label: "Okno popytu" },
  { key: "finanse", label: "Finanse (bez D11)" },
] as const;

function prepare(params: URLSearchParams) {
  const state: HarnessState = pickState(params.get("state"), KNOWN, "dzialy");
  const today = warsawToday();
  const org = clientOrgWithHealth(today);
  const map = peopleTechMap(today);
  const client = harnessQueryClient();
  client.setQueryData(hrKeys.config, hrConfig());
  client.setQueryData(clientPeopleKeys.org(ORG_CLIENT.id), org);
  client.setQueryData(careKeys.clientMap(ORG_CLIENT.id), map);
  client.setQueryData(careKeys.clientUnlinkedCards(ORG_CLIENT.id), {
    items: [],
    contracts: [],
    can_link: true,
  });
  client.setQueryData(careKeys.owners, CARE_OWNERS);
  seedStructure(client, today);
  return {
    user: state === "finanse" ? HR_CAST.piotr : HR_CAST.kamil,
    client,
    value: { state, consultants: org.consultants_count, people: org.people_count },
  };
}

/** Uproszczony nagłówek profilu klienta z paskiem zakładek — tylko kontekst. */
function ClientHeader({ people, consultants }: { people: number; consultants: number }) {
  const tabs = ["Profil", "Zamówienia", "Delivery Lead", "Kontakty klienta", "Ludzie i technologie", "Umowy"];
  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2.5 sm:px-5">
        <span className="text-xs text-muted-foreground">Klienci</span>
        <span aria-hidden="true" className="text-xs text-muted-foreground">
          /
        </span>
        <h2 className="font-display text-lg font-semibold text-foreground">{ORG_CLIENT.name}</h2>
        <span className="text-xs text-muted-foreground">
          {people} osób klienta · {consultants} naszych konsultantów
        </span>
      </div>
      <div className="flex overflow-x-auto border-t border-border px-3 text-[13px] sm:px-5">
        {tabs.map((tab) => (
          <span
            key={tab}
            className={
              tab === "Ludzie i technologie"
                ? "inline-block shrink-0 border-b-2 border-primary px-3 py-2 font-semibold text-foreground"
                : "inline-block shrink-0 border-b-2 border-transparent px-3 py-2 text-muted-foreground"
            }
          >
            {tab}
          </span>
        ))}
        <span className="inline-block shrink-0 px-3 py-2 text-muted-foreground">Więcej ▾</span>
      </div>
    </div>
  );
}

function PeopleTechHarness({ state }: { state: HarnessState }) {
  const [view, setView] = useState<PeopleView>(state === "drzewo" ? "drzewo" : "dzialy");
  const [demandOpen, setDemandOpen] = useState(state === "popyt");
  return (
    <>
      <div data-harness-state={state}>
        <ClientPeopleTechTab
          clientId={ORG_CLIENT.id}
          view={view}
          onViewChange={setView}
          proposalsOpen={state === "zatwierdz"}
        />
      </div>
      {demandOpen ? (
        <ClientFeedbackDialog
          clientId={ORG_CLIENT.id}
          clientName={ORG_CLIENT.name}
          manager={null}
          open
          onOpenChange={(open) => setDemandOpen(open)}
          demand={{
            key: `demand:${ORG_CLIENT.id}:301:77`,
            roles: ["Java Developer", "QA"],
            area: { id: 301, name: "Płatności" },
            source: "widział",
          }}
        />
      ) : null}
    </>
  );
}

export default function HrClientPeoplePreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Ludzie i technologie"
      note="Dane fikcyjne, bez zapytań. Ogląda Delivery Lead klienta (w stanie „Finanse” — kontroler finansowy spoza kręgu D11); działy, drzewo osób, propozycje automatu i okno popytu."
      states={STATES}
      current={ready.value.state}
    >
      <div className="space-y-4">
        <ClientHeader consultants={ready.value.consultants} people={ready.value.people} />
        <PeopleTechHarness state={ready.value.state} />
      </div>
    </HrHarnessShell>
  );
}
