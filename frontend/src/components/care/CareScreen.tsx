"use client";

import { useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { useCareSummary, useCareWeek } from "@/lib/api/care";
import { useUrlWriter } from "@/lib/url-selection";

import { MyConsultantsPanel } from "./MyConsultantsPanel";
import { RedeployPanel } from "./RedeployPanel";
import { SkillReviewPanel } from "./SkillReviewPanel";
import { WeekPanel } from "./week/WeekPanel";

export type CareTab = "week" | "contracts" | "redeploy" | "review";

/** Zakładka z `?tab=`; dawne `mine` („Moi konsultanci”) to dziś „Wszystkie kontrakty”. */
export function careTabFrom(value: string | null | undefined): CareTab {
  if (value === "redeploy" || value === "review" || value === "contracts") return value;
  if (value === "mine") return "contracts";
  return "week";
}

function CareTabs() {
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const summary = useCareSummary();
  // Licznik zaległych przy „Ten tydzień” — to samo zapytanie co lista (domyślny zakres).
  const week = useCareWeek("mine", null);
  const tab = careTabFrom(searchParams?.get("tab"));
  const select = (next: string) => {
    const params = new URLSearchParams(window.location.search);
    if (next === "week") params.delete("tab");
    else params.set("tab", next);
    // Panel osi należy do listy tygodnia.
    params.delete("contract");
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
        { value: "contracts", label: "Wszystkie kontrakty" },
        { value: "redeploy", label: "Do przepięcia", count: summary.data?.redeploy_active },
        {
          value: "review",
          label: "Technologie do przejrzenia",
          count: summary.data?.skill_review_open,
        },
      ]}
    >
      <div className="pt-3">
        {tab === "week" ? <WeekPanel /> : null}
        {tab === "contracts" ? <MyConsultantsPanel /> : null}
        {tab === "redeploy" ? <RedeployPanel /> : null}
        {tab === "review" ? <SkillReviewPanel /> : null}
      </div>
    </TabbedNav>
  );
}

/** `/care` — opiekun: kolejka na ten tydzień, wszystkie kontrakty i kolejki. */
export function CareScreen() {
  return (
    <HrConfigGate>
      {(config) => (
        <div className="space-y-4">
          <PageHeader
            title="Opieka nad konsultantami"
            description="Kontakty z konsultantami i menedżerami u klientów, przepięcia i technologie z rozmów."
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
