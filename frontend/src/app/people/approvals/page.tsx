"use client";

import { Suspense } from "react";

import { PageHeader } from "@/components/ds/PageHeader";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { ApprovalsScreen } from "@/components/hr/leave/ApprovalsScreen";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";

// „Ludzie → Akceptacje” (16.10.2026): wnioski urlopowe i timesheety zespołu do
// decyzji, historia i wpis nieobecności za pracownika. O dostępie decyduje
// serwer (przełożony swojego zespołu, Kadry i admin wszystkich; nikt siebie).
// `ApprovalsScreen` czyta z adresu miesiąc i osobę (linki z powiadomień).
export default function PeopleApprovalsPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Ładowanie…</div>}>
      <HrConfigGate>
        {(config) => (
          <div className="space-y-4">
            <PageHeader
              title="Akceptacje"
              description="Wnioski i timesheety Twojego zespołu do decyzji, historia nieobecności."
              density="compact"
            />
            <PeopleSectionNav config={config} active="approvals" />
            <ApprovalsScreen config={config} />
          </div>
        )}
      </HrConfigGate>
    </Suspense>
  );
}
