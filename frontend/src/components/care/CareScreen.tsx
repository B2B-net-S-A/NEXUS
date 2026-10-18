"use client";

import { useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { useCareSummary, useCareWeek } from "@/lib/api/care";
import { canReadClientPeople } from "@/lib/api/client-people";
import { useStructureSummary } from "@/lib/api/structure-proposals";
import { useAuthStore } from "@/store/auth";
import { useUrlWriter } from "@/lib/url-selection";

import { AnnouncementsTab } from "./announcements/AnnouncementsTab";
import { AssignmentPanel } from "./AssignmentPanel";
import { ConsultantsPanel } from "./ConsultantsPanel";
import { RedeployPanel } from "./RedeployPanel";
import { SkillReviewPanel } from "./SkillReviewPanel";
import { StructureTab } from "./structure/StructureTab";
import { WeekPanel } from "./week/WeekPanel";

export type CareTab =
  | "week"
  | "consultants"
  | "structure"
  | "assignment"
  | "announcements"
  | "redeploy"
  | "review";

const TABS: readonly CareTab[] = [
  "week",
  "consultants",
  "structure",
  "assignment",
  "announcements",
  "redeploy",
  "review",
];

/**
 * Zakładka z `?tab=`; dawne „Wszystkie kontrakty” (`contracts`) i „Moi
 * konsultanci” (`mine`) to dziś „Konsultanci” (etap 3, M1).
 */
export function careTabFrom(value: string | null | undefined): CareTab {
  if (value === "contracts" || value === "mine") return "consultants";
  return TABS.find((tab) => tab === value) ?? "week";
}

function CareTabs() {
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const summary = useCareSummary();
  // Licznik zaległych przy „Ten tydzień” — to samo zapytanie co lista (domyślny zakres).
  const week = useCareWeek("mine", null);
  // „Struktura u klientów” — krąg D11 (Finanse i Kadry jej nie widzą, serwer odmawia 403).
  const user = useAuthStore((s) => s.user);
  const peopleOpen = canReadClientPeople(user);
  const structure = useStructureSummary(peopleOpen);
  const requested = careTabFrom(searchParams?.get("tab"));
  const tab = requested === "structure" && !peopleOpen ? "week" : requested;
  const select = (next: string) => {
    const params = new URLSearchParams(window.location.search);
    if (next === "week") params.delete("tab");
    else params.set("tab", next);
    // Panel osi należy do listy tygodnia, komunikat — do „Komunikatów”.
    params.delete("contract");
    params.delete("announcement");
    params.delete("client");
    const qs = params.toString();
    replaceUrl(qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  };
  return (
    <TabbedNav
      ariaLabel="Opieka nad konsultantami"
      value={tab}
      onValueChange={select}
      tabs={[
        { value: "week", label: "Ten tydzień", count: week.data?.counts.overdue || undefined },
        { value: "consultants", label: "Konsultanci" },
        ...(peopleOpen
          ? [
              {
                value: "structure",
                label: "Struktura u klientów",
                count: structure.data?.totals.open || undefined,
              },
            ]
          : []),
        { value: "assignment", label: "Przydział" },
        { value: "announcements", label: "Komunikaty" },
        { value: "redeploy", label: "Do przepięcia", count: summary.data?.redeploy_active },
        {
          value: "review",
          label: "Technologie",
          count: summary.data?.skill_review_open,
        },
      ]}
    >
      <div className="pt-3">
        {tab === "week" ? <WeekPanel /> : null}
        {tab === "consultants" ? <ConsultantsPanel /> : null}
        {tab === "structure" ? <StructureTab /> : null}
        {tab === "assignment" ? <AssignmentPanel /> : null}
        {tab === "announcements" ? <AnnouncementsTab /> : null}
        {tab === "redeploy" ? <RedeployPanel /> : null}
        {tab === "review" ? <SkillReviewPanel /> : null}
      </div>
    </TabbedNav>
  );
}

/** `/care` — opiekun: kolejka na ten tydzień, konsultanci z rytmem, przydział, komunikaty i kolejki. */
export function CareScreen() {
  return (
    <HrConfigGate>
      {(config) => (
        <div className="space-y-4">
          <PageHeader
            title="Opieka nad konsultantami"
            description="Kontakty z konsultantami i menedżerami u klientów, rytm i opiekunowie, przepięcia i technologie z rozmów."
            density="compact"
          />
          {config.open_modules.care ? (
            <CareTabs />
          ) : (
            <QueryStateNotice
              state="not_found"
              description="Moduł opieki nie jest jeszcze włączony."
            />
          )}
        </div>
      )}
    </HrConfigGate>
  );
}
