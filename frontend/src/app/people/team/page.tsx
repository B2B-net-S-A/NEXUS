"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/ds/PageHeader";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";
import { TeamScreen } from "@/components/hr/team/TeamScreen";

// „Ludzie → Mój zespół” (etap 2, D6, 17.10.2026; układ z makiety 19.10.2026):
// przełożony o swoich ludziach — pasek „Dziś”, sprawy do decyzji z akceptacją na
// miejscu, mini-tydzień, miesiąc, premie bez stawek. Kadry i admin oglądają
// zespół innego przełożonego (`?manager=`).
function TeamPageBody() {
  const params = useSearchParams();
  const raw = Number(params.get("manager"));
  const manager = Number.isInteger(raw) && raw > 0 ? raw : null;
  return (
    <HrConfigGate>
      {(config) => (
        <div className="space-y-4">
          <PageHeader
            title="Mój zespół"
            description="Kto jest dziś, co czeka na Twoją decyzję i jak idzie miesiąc."
            density="compact"
          />
          <PeopleSectionNav config={config} active="team" />
          <TeamScreen config={config} initialManager={manager} />
        </div>
      )}
    </HrConfigGate>
  );
}

export default function PeopleTeamPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Ładowanie…</div>}>
      <TeamPageBody />
    </Suspense>
  );
}
