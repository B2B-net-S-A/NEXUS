"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Megaphone } from "lucide-react";

import { PortalFaqTab } from "@/components/back-office/PortalFaqTab";
import { QualityTab } from "@/components/back-office/QualityTab";
import { QueueBoard } from "@/components/back-office/QueueBoard";
import { ReviewPanel } from "@/components/back-office/ReviewPanel";
import { TeamsPanel } from "@/components/back-office/TeamsPanel";
import { TalksTab } from "@/components/back-office/TalksTab";
import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { WorkBoard } from "@/components/work-board/WorkBoard";
import { canSeeCareBoard } from "@/components/work-board/care-access";
import { listFilterFromParam } from "@/components/work-board/work-board-model";
import { useCareClients, useCareConsultants } from "@/lib/api/care";
import { useAnnouncements } from "@/lib/api/care-announcements";
import { useCareBoard, type CareBoardCard } from "@/lib/api/care-board";
import { casesInCare, type HrConfig } from "@/lib/api/hr";
import { canSeeSettingsItem, findSettingsItem, settingsItemHref } from "@/lib/settings-registry";
import { useUrlWriter } from "@/lib/url-selection";
import { useAuthStore } from "@/store/auth";

import { AnnouncementsTab } from "./announcements/AnnouncementsTab";
import { consultantsIn } from "./cadence-format";
import { ConsultantCardPanel } from "./card/ConsultantCardPanel";
import { FrontOfficeDialog } from "./card/FrontOfficeDialog";
import { ClientFeedbackDialog, type ClientFeedbackDialogProps } from "./ClientFeedbackDialog";
import { ClientsPanel } from "./clients/ClientsPanel";
import { ConsultantsPanel, type ConsultantsFilter } from "./ConsultantsPanel";
import { ConversationDialog } from "./ConversationDialog";
import { CareTeamPanel } from "./team/CareTeamPanel";

export type CareTab =
  | "todo"
  | "consultants"
  | "clients"
  | "team"
  | "announcements"
  | "teams"
  | "review"
  | "talks"
  | "quality"
  | "faq";

export interface CareRoute {
  tab: CareTab;
  /** Filtr startowy „Konsultantów” (dawne „Do przepięcia”). */
  filter?: ConsultantsFilter;
  /** Adres poza `/care`, na który stary link prowadzi teraz (router.replace). */
  redirect?: string;
}

/**
 * Zakładka z `?tab=` i przekierowania starych adresów (22.10.2026):
 * „Ten tydzień” (`week`, brak) → „Do zrobienia”; `contracts`, `mine` →
 * „Konsultanci”; `redeploy` → „Konsultanci” z filtrem „Do przepięcia” (karty
 * „Decyzja” stoją na tablicy); `assignment` → „Zespół opiekunów”;
 * `structure` → „Klienci” (z `client` — „Ludzie i technologie” klienta);
 * `review` (kolejka nazw technologii) → Ustawienia → Słownik umiejętności
 * (admin, HoR — `canSeeSkills`), a TCM bez dostępu do Słownika → „Nazwy
 * z rozmów do przejrzenia”.
 */
export function careRouteFrom(
  params: URLSearchParams | null | undefined,
  { canSeeSkills = true }: { canSeeSkills?: boolean } = {},
): CareRoute {
  const value = params?.get("tab") ?? null;
  switch (value) {
    case "consultants":
    case "contracts":
    case "mine":
      return { tab: "consultants" };
    case "redeploy":
      return { tab: "consultants", filter: "redeploy" };
    case "clients":
      return { tab: "clients" };
    case "structure": {
      const client = Number(params?.get("client"));
      return Number.isInteger(client) && client > 0
        ? { tab: "clients", redirect: `/clients/${client}?tab=ludzie` }
        : { tab: "clients" };
    }
    case "team":
    case "assignment":
      return { tab: "team" };
    case "announcements":
      return { tab: "announcements" };
    case "teams":
      return { tab: "teams" };
    case "przeglad":
      return { tab: "review" };
    case "talks":
      return { tab: "talks" };
    case "quality":
      return { tab: "quality" };
    case "faq":
      return { tab: "faq" };
    case "review": {
      const target = findSettingsItem(canSeeSkills ? "skills" : "skills-review");
      return { tab: "todo", redirect: target ? settingsItemHref(target) : "/settings" };
    }
    default:
      return { tab: "todo" };
  }
}

/** `?contract=` — karta konsultanta otwarta z linku (dzwonek, tablica, lista). */
export function contractParam(value: string | null | undefined): number | null {
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
}

/** Zespół opiekunów — `require_hr_care_assigner`: head back office i admin. */
export function canSeeTeam(config: Pick<HrConfig, "me">): boolean {
  return Boolean(config.me.back_office_head || config.me.is_admin);
}

/** Kierownik kolejki: head back office, admin (zastępcy pilnuje serwer przy trasach). */
function canSeeBackOfficeLead(config: Pick<HrConfig, "me">): boolean {
  return Boolean(config.me.back_office_lead || config.me.back_office_head || config.me.is_admin);
}

const TITLE = "Opieka nad konsultantami";
const DESCRIPTION =
  "Rozmowy, sprawy i decyzje na jednej tablicy; konsultanci ze zdrowiem relacji; wiedza o klientach.";
const CASES_ONLY_DESCRIPTION = "Sprawy administracja@ na jednej tablicy.";
const BACK_OFFICE_TITLE = "Back office";
const BACK_OFFICE_DESCRIPTION =
  "Kolejka spraw czterech zespołów: każdy bierze swoje, a kierownik widzi całość.";

type FeedbackTarget = Omit<ClientFeedbackDialogProps, "open" | "onOpenChange">;

function feedbackTarget(card: CareBoardCard, withDemand: boolean): FeedbackTarget | null {
  if (card.client_id == null) return null;
  return {
    clientId: card.client_id,
    clientName: card.client_name ?? "Klient",
    manager: card.manager ? { id: card.manager.contact_id, name: card.manager.name } : null,
    consultants: (card.consultants ?? []).map((person) => ({
      contract_id: person.contract_id,
      candidate_id: null,
      candidate_name: person.name,
      role: null,
      end_date: null,
      end_source: null,
      last_feedback: null,
    })),
    demand:
      withDemand && card.demand
        ? { key: card.key, roles: card.demand.roles, area: card.demand.area, source: card.demand.source }
        : null,
  };
}

function CareTabs({ config }: { config: HrConfig }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const user = useAuthStore((s) => s.user);
  const skillsItem = findSettingsItem("skills");
  const route = careRouteFrom(searchParams, {
    canSeeSkills: skillsItem ? canSeeSettingsItem(user, skillsItem, { hrProgram: config.program }) : false,
  });
  // Bez roli opieki (same sprawy administracja@, od 22.10.2026 tu zamiast
  // „Ludzie → Sprawy”) jest tylko „Do zrobienia” — reszty serwer i tak odmawia.
  const careRole = canSeeCareBoard(user, config);
  // Moduł `back_office`: główna zakładka to kolejka zespołów. Stare linki z kartą
  // albo filtrem kanbanu (`?card=`, `?filter=`) dalej otwierają kanban.
  const kanbanLink = Boolean(searchParams?.get("card") || searchParams?.get("filter"));
  const teamOpen = canSeeTeam(config);
  // Bez miejsca w zespole serwer odmawia kolejce: ta osoba pracuje na kanbanie jak dotąd.
  const backOffice = config.open_modules.back_office && config.me.back_office_member === true;
  const leadOpen = backOffice && canSeeBackOfficeLead(config);
  const leadTab = route.tab === "teams" || route.tab === "review";
  // Zakładki portalu konsultanta stoją za modułem `back_office`; serwer ma własne bramki.
  const portalTab = route.tab === "talks" || route.tab === "quality" || route.tab === "faq";
  const tab: CareTab =
    (leadTab && leadOpen) || (portalTab && backOffice)
      ? route.tab
      : leadTab || portalTab || !careRole || (route.tab === "team" && !teamOpen)
        ? "todo"
        : route.tab;
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const announcements = useAnnouncements(careRole);
  const pendingApprovals = (announcements.data?.items ?? []).filter((row) => row.can_approve).length;
  // Liczniki zakładek (P1: „Do zrobienia 7 · Konsultanci 42 · Klienci 9”) — te same
  // zapytania co zakładki (wspólny cache), liczba dopiero po udanym odczycie.
  // Bez roli opieki nie pytamy (serwer odmawia) — zakładki i tak ich nie ma.
  const todoCount = useCareBoard("mine", careRole);
  const consultantsCount = useCareConsultants(careRole);
  const clientsCount = useCareClients(scope, careRole);
  // `?filter=` — chip kolejki „Do zrobienia” z linku (dzwonki).
  const listFilter = listFilterFromParam(searchParams?.get("filter"));

  // Karta konsultanta z adresu (link z dzwonka, tablicy) i z kliknięcia; adres
  // pisze `useUrlWriter` (natywna historia), więc stan trzymamy też lokalnie.
  const urlContract = contractParam(searchParams?.get("contract"));
  const [contractId, setContractId] = useState<number | null>(urlContract);
  useEffect(() => setContractId(urlContract), [urlContract]);
  const cardKey = searchParams?.get("card") ?? null;

  const [talk, setTalk] = useState<{ contractId: number; planItemId: number | null } | null>(null);
  const [frontOffice, setFrontOffice] = useState<number | null>(null);
  const [feedback, setFeedback] = useState<FeedbackTarget | null>(null);

  useEffect(() => {
    if (route.redirect) router.replace(route.redirect);
  }, [route.redirect, router]);

  const writeParams = (change: (params: URLSearchParams) => void) => {
    const params = new URLSearchParams(window.location.search);
    change(params);
    const qs = params.toString();
    replaceUrl(qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  };
  const select = (next: string) =>
    writeParams((params) => {
      if (next === "todo") params.delete("tab");
      else params.set("tab", next);
      // Karta i komunikat należą do zakładki, z której je otwarto.
      params.delete("announcement");
      params.delete("client");
      params.delete("card");
      params.delete("filter");
    });
  const openContract = (id: number | null) => {
    setContractId(id);
    writeParams((params) => {
      if (id == null) params.delete("contract");
      else params.set("contract", String(id));
    });
  };
  const openAnnouncement = (id: number) =>
    writeParams((params) => {
      params.set("tab", "announcements");
      params.set("announcement", String(id));
      params.delete("contract");
    });

  const tabs = [
    {
      value: "todo",
      label: backOffice ? "Kolejka" : "Do zrobienia",
      count: !backOffice && careRole && todoCount.isSuccess ? todoCount.data.cards.length : undefined,
    },
    ...(careRole
      ? [
          {
            value: "consultants",
            label: "Konsultanci",
            count: consultantsCount.isSuccess ? consultantsIn(consultantsCount.data.items, scope).length : undefined,
          },
          {
            value: "clients",
            label: "Klienci",
            count: clientsCount.isSuccess ? clientsCount.data.rows.length : undefined,
          },
          ...(teamOpen ? [{ value: "team", label: "Zespół opiekunów" }] : []),
        ]
      : []),
    ...(backOffice
      ? [
          { value: "talks", label: "Rozmowy" },
          { value: "quality", label: "Jakość" },
          { value: "faq", label: "FAQ portalu" },
        ]
      : []),
    ...(leadOpen
      ? [
          { value: "teams", label: "Zespoły" },
          { value: "przeglad", label: "Przegląd" },
        ]
      : []),
  ];
  const scoped = tab === "consultants" || tab === "clients";

  const actions = (
    <div className="flex flex-wrap items-center gap-2">
      {scoped ? (
        <SegmentedRadio
          label="Zakres"
          size="sm"
          value={scope}
          onChange={setScope}
          options={[
            { value: "mine", label: "Moi" },
            { value: "all", label: "Mój zakres" },
          ]}
        />
      ) : null}
      <Button
        size="sm"
        variant={tab === "announcements" ? "primary" : "outline"}
        aria-pressed={tab === "announcements"}
        onClick={() => select(tab === "announcements" ? "todo" : "announcements")}
      >
        <Megaphone aria-hidden className="size-4" />
        Komunikaty
        {pendingApprovals ? (
          <span
            className="rounded-full border border-warning/25 bg-warning-muted px-1.5 text-[11px] font-semibold tabular-nums text-warning-muted-foreground"
            aria-label={`do zatwierdzenia: ${pendingApprovals}`}
          >
            {pendingApprovals}
          </span>
        ) : null}
      </Button>
    </div>
  );

  const kanban = (
    <div data-help="hr.care.board">
      <WorkBoard
        scope="care"
        config={config}
        initialSelectedKey={cardKey}
        initialFilter={listFilter}
        onOpenContract={openContract}
        onCloseSelected={() => writeParams((params) => params.delete("card"))}
        onOpenConversation={(id, planItemId) => setTalk({ contractId: id, planItemId: planItemId ?? null })}
        onOpenFrontOffice={(id) => setFrontOffice(id)}
        onOpenFeedback={(card) => setFeedback(feedbackTarget(card, false))}
        onOpenDemand={(card) => setFeedback(feedbackTarget(card, true))}
      />
    </div>
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title={backOffice ? BACK_OFFICE_TITLE : TITLE}
        description={backOffice ? BACK_OFFICE_DESCRIPTION : careRole ? DESCRIPTION : CASES_ONLY_DESCRIPTION}
        density="compact"
        actions={careRole ? actions : undefined}
      />
      <TabbedNav
        ariaLabel={backOffice ? "Back office" : "Opieka nad konsultantami"}
        value={tab === "review" ? "przeglad" : tab}
        onValueChange={select}
        tabs={tabs}
      >
        <div className="pt-3">
          {tab === "todo" && backOffice && !kanbanLink ? (
            <QueueBoard careStatusBoard={careRole || casesInCare(config) ? kanban : null} />
          ) : null}
          {tab === "todo" && (!backOffice || kanbanLink) ? kanban : null}
          {tab === "consultants" ? (
            <ConsultantsPanel
              key={route.filter ?? "all"}
              scope={scope}
              onScopeChange={setScope}
              onOpenContract={openContract}
              onOpenAnnouncement={openAnnouncement}
              canAnnounce={announcements.data?.me.can_author ?? false}
              canAssign={teamOpen}
              initialFilter={route.filter}
              selectedId={contractId}
            />
          ) : null}
          {tab === "clients" ? <ClientsPanel scope={scope} onOpenContract={openContract} /> : null}
          {tab === "team" ? <CareTeamPanel /> : null}
          {tab === "teams" ? <TeamsPanel /> : null}
          {tab === "review" ? <ReviewPanel /> : null}
          {tab === "announcements" ? <AnnouncementsTab /> : null}
          {tab === "talks" ? <TalksTab /> : null}
          {tab === "quality" ? <QualityTab /> : null}
          {tab === "faq" ? <PortalFaqTab /> : null}
        </div>
      </TabbedNav>
      <ConsultantCardPanel contractId={contractId} onClose={() => openContract(null)} />
      {talk ? (
        <ConversationDialog
          contractId={talk.contractId}
          planItem={talk.planItemId != null ? { id: talk.planItemId } : null}
          open
          onOpenChange={(open) => {
            if (!open) setTalk(null);
          }}
        />
      ) : null}
      {frontOffice != null ? (
        <FrontOfficeDialog
          contractId={frontOffice}
          open
          onOpenChange={(open) => {
            if (!open) setFrontOffice(null);
          }}
        />
      ) : null}
      {feedback ? (
        <ClientFeedbackDialog
          {...feedback}
          open
          onOpenChange={(open) => {
            if (!open) setFeedback(null);
          }}
        />
      ) : null}
    </div>
  );
}

/**
 * `/care` — Opieka nad konsultantami (22.10.2026): „Do zrobienia” (tablica
 * kart opieki i spraw), „Konsultanci” (rytm i zdrowie relacji), „Klienci”
 * (wiedza, popyt, kończący), „Zespół opiekunów” (head back office i admin).
 * „Komunikaty” to przycisk w nagłówku z liczbą do zatwierdzenia.
 * `?contract=<id>` otwiera kartę konsultanta na każdej zakładce, `?card=<klucz>`
 * — panel karty tablicy, `?filter=po-terminie|do-piatku|rozmowy|opinie|decyzje|
 * dane|popyt` — chip kolejki „Do zrobienia” (linki z dzwonków).
 */
export function CareScreen() {
  return (
    <HrConfigGate>
      {(config) => (
        config.open_modules.care || config.open_modules.back_office ? (
          <CareTabs config={config} />
        ) : (
          <div className="space-y-4">
            <PageHeader title={TITLE} description={DESCRIPTION} density="compact" />
            <QueryStateNotice state="not_found" description="Moduł opieki nie jest jeszcze włączony." />
          </div>
        )
      )}
    </HrConfigGate>
  );
}
