"use client";

import { useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { useCareSummary } from "@/lib/api/care";
import { useUrlWriter } from "@/lib/url-selection";

import { MyConsultantsPanel } from "./MyConsultantsPanel";
import { RedeployPanel } from "./RedeployPanel";
import { SkillReviewPanel } from "./SkillReviewPanel";

export type CareTab = "mine" | "redeploy" | "review";

export function careTabFrom(value: string | null | undefined): CareTab {
  return value === "redeploy" || value === "review" ? value : "mine";
}

function CareTabs() {
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const summary = useCareSummary();
  const tab = careTabFrom(searchParams?.get("tab"));
  const select = (next: string) => {
    const params = new URLSearchParams(window.location.search);
    if (next === "mine") params.delete("tab");
    else params.set("tab", next);
    const qs = params.toString();
    replaceUrl(qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  };
  return (
    <TabbedNav
      ariaLabel="Opieka nad konsultantami"
      value={tab}
      onValueChange={select}
      tabs={[
        { value: "mine", label: "Moi konsultanci" },
        { value: "redeploy", label: "Do przepięcia", count: summary.data?.redeploy_active },
        {
          value: "review",
          label: "Technologie do przejrzenia",
          count: summary.data?.skill_review_open,
        },
      ]}
    >
      <div className="pt-3">
        {tab === "mine" ? <MyConsultantsPanel /> : null}
        {tab === "redeploy" ? <RedeployPanel /> : null}
        {tab === "review" ? <SkillReviewPanel /> : null}
      </div>
    </TabbedNav>
  );
}

/** `/care` — opiekun: lista konsultantów z najbliższym kontaktem i kolejki. */
export function CareScreen() {
  return (
    <HrConfigGate>
      {(config) => (
        <div className="space-y-4">
          <PageHeader
            title="Opieka nad konsultantami"
            description="Kontakty z konsultantami u klientów, przepięcia i technologie z rozmów."
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
