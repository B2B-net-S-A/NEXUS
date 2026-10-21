"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Megaphone } from "lucide-react";

import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { WorkBoard } from "@/components/work-board/WorkBoard";
import { useAnnouncements } from "@/lib/api/care-announcements";
import type { CareBoardCard } from "@/lib/api/care-board";
import type { HrConfig } from "@/lib/api/hr";
import { findSettingsItem, settingsItemHref } from "@/lib/settings-registry";
import { useUrlWriter } from "@/lib/url-selection";

import { AnnouncementsTab } from "./announcements/AnnouncementsTab";
import { ConsultantCardPanel } from "./card/ConsultantCardPanel";
import { FrontOfficeDialog } from "./card/FrontOfficeDialog";
import { ClientFeedbackDialog, type ClientFeedbackDialogProps } from "./ClientFeedbackDialog";
import { ClientsPanel } from "./clients/ClientsPanel";
import { ConsultantsPanel, type ConsultantsFilter } from "./ConsultantsPanel";
import { ConversationDialog } from "./ConversationDialog";
import { CareTeamPanel } from "./team/CareTeamPanel";

export type CareTab = "todo" | "consultants" | "clients" | "team" | "announcements";

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
 * `review` (kolejka nazw technologii) → Ustawienia → Słownik umiejętności.
 */
export function careRouteFrom(params: URLSearchParams | null | undefined): CareRoute {
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
    case "review": {
      const skills = findSettingsItem("skills");
      return { tab: "todo", redirect: skills ? settingsItemHref(skills) : "/settings" };
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

const TITLE = "Opieka nad konsultantami";
const DESCRIPTION =
  "Rozmowy, sprawy i decyzje na jednej tablicy; konsultanci ze zdrowiem relacji; wiedza o klientach.";

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
  const route = careRouteFrom(searchParams);
  const teamOpen = canSeeTeam(config);
  const tab: CareTab = route.tab === "team" && !teamOpen ? "todo" : route.tab;
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const announcements = useAnnouncements();
  const pendingApprovals = (announcements.data?.items ?? []).filter((row) => row.can_approve).length;

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
    { value: "todo", label: "Do zrobienia" },
    { value: "consultants", label: "Konsultanci" },
    { value: "clients", label: "Klienci" },
    ...(teamOpen ? [{ value: "team", label: "Zespół opiekunów" }] : []),
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

  return (
    <div className="space-y-4">
      <PageHeader title={TITLE} description={DESCRIPTION} density="compact" actions={actions} />
      <TabbedNav ariaLabel="Opieka nad konsultantami" value={tab} onValueChange={select} tabs={tabs}>
        <div className="pt-3">
          {tab === "todo" ? (
            <WorkBoard
              scope="care"
              config={config}
              initialSelectedKey={cardKey}
              onOpenConversation={(id, planItemId) => setTalk({ contractId: id, planItemId: planItemId ?? null })}
              onOpenFrontOffice={(id) => setFrontOffice(id)}
              onOpenFeedback={(card) => setFeedback(feedbackTarget(card, false))}
              onOpenDemand={(card) => setFeedback(feedbackTarget(card, true))}
            />
          ) : null}
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
          {tab === "announcements" ? <AnnouncementsTab /> : null}
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
 * `?contract=<id>` otwiera kartę konsultanta na każdej zakładce.
 */
export function CareScreen() {
  return (
    <HrConfigGate>
      {(config) => (
        config.open_modules.care ? (
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
