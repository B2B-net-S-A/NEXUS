"use client";

/**
 * Harness „Opieka nad konsultantami” (przebudowa 22.10.2026, makiety
 * 2yNppKPWBQcstvBK3YiaxV) — prawdziwe ekrany na zasianym cache, ZERO zapytań
 * (`hr-harness.tsx`). Ogląda Natalia (Talent Community Manager, opiekunka);
 * w stanie `team` — jako head back office. Daty liczymy od „dziś”
 * przeglądarki (`fixtures.ts`, kontrakt Michała w 45. dniu współpracy).
 *
 * Stany (`?state=`):
 * - `tab` (domyślnie) — zakładka „Opieka” kontraktu = karta konsultanta na
 *   pełną szerokość: zdrowie, cztery liczby, „Następny krok”, „Co wiemy
 *   o projekcie”, sprawy, „Historia” z filtrami, plan kontaktów zwinięty;
 * - `techcard` — edycja starej karty technologicznej z „Historii”
 *   (`TechCardDialog` — przycisk „Karta technologiczna” zniknął);
 * - `conversation` — okno „Rozmowa” Michała: lewa kolumna dzisiejsza rozmowa,
 *   prawa „Co u klienta”, pytania z mapy klienta, „Coś do załatwienia?”;
 * - `list` — `/care` „Do zrobienia” (tablica opieki); `&tab=consultants`,
 *   `&tab=clients`, `&tab=announcements` — pozostałe zakładki, `&contract=<id>`
 *   — karta konsultanta w panelu (4504 — „Przekaż do front office”);
 * - `team` — „Zespół opiekunów” (head back office): opiekunowie z zaległymi
 *   i portfelem, „Ustawienia przydziału” zwinięte, przydział;
 * - `cadence` — „Konsultanci” z otwartym oknem „Rytm kontaktu” Bartosza.
 * Stare adresy (`&tab=week|contracts|mine|redeploy|assignment|structure`)
 * prowadzą do nowych zakładek tak jak na `/care`.
 */

import { Suspense, useState } from "react";

import { CadenceDialog } from "@/components/care/CadenceDialog";
import { CareScreen } from "@/components/care/CareScreen";
import { ContractCareTab } from "@/components/care/ContractCareTab";
import { ConversationDialog } from "@/components/care/ConversationDialog";
import { TechCardDialog } from "@/components/care/TechCardDialog";
import { careKeys } from "@/lib/api/care";
import { announcementKeys } from "@/lib/api/care-announcements";
import { careBoardKeys } from "@/lib/api/care-board";
import { clientPeopleKeys } from "@/lib/api/client-people";
import { hrKeys } from "@/lib/api/hr";
import { formatIsoDatePl } from "@/lib/date-pl";
import { warsawToday } from "@/lib/warsaw-date";

import { detail as announcementDetail, list as announcementList } from "../hr-announcements/fixtures";
import { careBoard } from "../hr-cases/care-fixtures";
import { weekEnd } from "../hr-cases/fixtures";
import { clientOrg } from "../hr-client-people/fixtures";
import { clientTechMap } from "../hr-client-tech/fixtures";
import { seedStructure } from "../hr-client-structure/fixtures";
import { HR_CAST, HR_CLIENTS, HR_CONSULTANTS, hrConfig } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";
import { cardTimeline, careClients, clientStateFor, consultantCards } from "./card-fixtures";
import {
  CARE_CLIENT,
  CARE_CONTRACT_ID,
  CARE_OWNERS,
  CARE_SUMMARY,
  CLIENT_AREAS,
  careTechCard,
  contractCare,
  contractStart,
  redeployQueue,
  skillReview,
} from "./fixtures";
import {
  BARTOSZ_CONTRACT,
  bartoszCadence,
  bartoszCadencePreview,
  careAssignment,
  careAutoAssignment,
  careConsultants,
  michalCadence,
} from "./rhythm-fixtures";
import { WEEK_HANDOFF_CONTRACT, karolinaFrontOffice, pawelFrontOffice, telecomTechMap } from "./week-fixtures";

const KNOWN = ["tab", "techcard", "conversation", "list", "team", "cadence"] as const;
type State = (typeof KNOWN)[number];

const STATES = [
  { key: "tab", label: "Karta w kontrakcie" },
  { key: "techcard", label: "Stara karta technologiczna" },
  { key: "conversation", label: "Okno „Rozmowa”" },
  { key: "list", label: "Do zrobienia (/care)" },
  { key: "panel", label: "Karta w panelu", href: `?state=list&tab=consultants&contract=${CARE_CONTRACT_ID}` },
  { key: "handoff", label: "Front office w panelu", href: `?state=list&contract=${WEEK_HANDOFF_CONTRACT}` },
  { key: "consultants", label: "Konsultanci", href: "?state=list&tab=consultants" },
  { key: "clients", label: "Klienci", href: "?state=list&tab=clients" },
  { key: "team", label: "Zespół opiekunów", href: "?state=team&tab=team" },
  { key: "cadence", label: "Zmiana rytmu", href: "?state=cadence&tab=consultants" },
] as const;

function prepare(params: URLSearchParams) {
  const state = pickState(params.get("state"), KNOWN, "tab");
  const today = warsawToday();
  const client = harnessQueryClient();
  const head = state === "team";
  client.setQueryData(hrKeys.config, hrConfig(head ? { back_office_head: true } : {}));
  client.setQueryData(careKeys.contract(CARE_CONTRACT_ID), contractCare(today));
  client.setQueryData(careKeys.owners, CARE_OWNERS);
  client.setQueryData(careKeys.summary, CARE_SUMMARY);
  client.setQueryData(careKeys.consultants, careConsultants(today));
  client.setQueryData(careKeys.assignment, careAssignment(today));
  client.setQueryData(careKeys.autoAssignment, careAutoAssignment(today));
  client.setQueryData(careKeys.cadence(BARTOSZ_CONTRACT), bartoszCadence(today));
  client.setQueryData(careKeys.cadence(BARTOSZ_CONTRACT, "biweekly"), bartoszCadencePreview(today));
  client.setQueryData(careKeys.cadence(CARE_CONTRACT_ID), michalCadence(today));
  for (const queue of ["active", "closed"] as const) {
    client.setQueryData(careKeys.redeploy(queue), redeployQueue(today, queue));
  }
  for (const review of ["open", "closed"] as const) {
    client.setQueryData(careKeys.skillReview(review), skillReview(today, review));
  }
  // Karta konsultanta, historia i okno rozmowy dla każdej osoby z „Konsultantów”.
  const rows = careConsultants(today).items;
  for (const card of consultantCards(today)) {
    client.setQueryData(careKeys.card(card.contract_id), card);
    client.setQueryData(careKeys.clientState(card.contract_id), clientStateFor(today, card.contract_id));
  }
  for (const row of rows) {
    client.setQueryData(careKeys.timeline(row.contract_id), cardTimeline(today, row));
  }
  client.setQueryData(careKeys.frontOffice(WEEK_HANDOFF_CONTRACT), pawelFrontOffice(today));
  client.setQueryData(careKeys.frontOffice(4502), karolinaFrontOffice(today));
  // „Co u klienta” → „zmień”: działy i osoby klienta (menedżer, „komu podlega”).
  for (const known of Object.values(HR_CLIENTS)) {
    client.setQueryData(careKeys.clientAreas(known.id), CLIENT_AREAS);
    client.setQueryData(clientPeopleKeys.org(known.id), {
      ...clientOrg(today),
      client_id: known.id,
      client_name: known.name,
    });
  }
  client.setQueryData(careKeys.clientMap(CARE_CLIENT.id), clientTechMap(today));
  client.setQueryData(careKeys.clientMap(HR_CLIENTS.telecom.id), telecomTechMap(today));
  for (const scope of ["mine", "all"] as const) {
    client.setQueryData(careKeys.clients(scope), careClients(today, scope));
    client.setQueryData(careBoardKeys.board(scope), careBoard(today, weekEnd(today), scope));
  }
  // „Komunikaty” w nagłówku: head back office ma komunikat do zatwierdzenia.
  const viewer = head ? "head" : "author";
  const announcements = announcementList(viewer);
  client.setQueryData(announcementKeys.list, announcements);
  for (const row of announcements.items) {
    client.setQueryData(announcementKeys.detail(row.id), announcementDetail(row.id, viewer));
  }
  seedStructure(client, today);
  return { user: HR_CAST.natalia, client, value: { state, today } };
}

/** Uproszczony nagłówek strony kontraktu — tylko kontekst dla zakładki. */
function ContractHeader({ start }: { start: string }) {
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <p className="text-xs text-muted-foreground">
          Kontrakty · B2B · aktywny od {formatIsoDatePl(start)}
        </p>
        <h2 className="text-xl font-semibold text-foreground">{HR_CONSULTANTS.michal.name}</h2>
        <p className="text-sm text-muted-foreground">Java Developer @ {CARE_CLIENT.name}</p>
      </div>
      <div className="border-b border-border text-[13px]">
        <span className="inline-block border-b-2 border-primary px-3 py-2 font-semibold text-foreground">
          Opieka
        </span>
      </div>
    </div>
  );
}

function OpenTechCard({ today }: { today: string }) {
  const [open, setOpen] = useState(true);
  if (!open) return null;
  return (
    <TechCardDialog
      contractId={CARE_CONTRACT_ID}
      clientId={CARE_CLIENT.id}
      card={careTechCard(today)}
      open
      onOpenChange={setOpen}
    />
  );
}

function OpenConversation() {
  const [open, setOpen] = useState(true);
  if (!open) return null;
  return (
    <ConversationDialog
      contractId={CARE_CONTRACT_ID}
      clientId={CARE_CLIENT.id}
      planItem={{ id: 5 }}
      open
      onOpenChange={setOpen}
    />
  );
}

function OpenCadence() {
  const [open, setOpen] = useState(true);
  if (!open) return null;
  return <CadenceDialog contractId={BARTOSZ_CONTRACT} open onOpenChange={setOpen} />;
}

function body(state: State, today: string) {
  if (state === "list" || state === "team" || state === "cadence") {
    return (
      <Suspense fallback={<HrHarnessLoading />}>
        <CareScreen />
        {state === "cadence" ? <OpenCadence /> : null}
      </Suspense>
    );
  }
  return (
    <div className="space-y-4">
      <ContractHeader start={contractStart(today)} />
      <ContractCareTab contractId={CARE_CONTRACT_ID} />
      {state === "techcard" ? <OpenTechCard today={today} /> : null}
      {state === "conversation" ? <OpenConversation /> : null}
    </div>
  );
}

export default function HrCarePreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { state, today } = ready.value;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Opieka nad konsultantami"
      note="Dane fikcyjne, bez zapytań. Ogląda opiekunka (Talent Community Manager); w „Zespole opiekunów” — head back office."
      states={STATES}
      current={state}
    >
      {body(state, today)}
    </HrHarnessShell>
  );
}
