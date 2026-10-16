"use client";

import { CasesBoard } from "@/components/admin-cases/CasesBoard";
import { PageHeader } from "@/components/ds/PageHeader";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";

// „Ludzie w NEXUSIE” (E6): sprawy skrzynki administracja@ — tablica statusów.
export default function PeopleCasesPage() {
  return (
    <HrConfigGate>
      {(config) => (
        <div className="space-y-4">
          <PageHeader
            title="Sprawy administracja@"
            description="Maile ze skrzynki, nowe kontrakty i odejścia zakładają sprawy same."
            density="compact"
          />
          <PeopleSectionNav config={config} active="cases" />
          <CasesBoard config={config} />
        </div>
      )}
    </HrConfigGate>
  );
}
