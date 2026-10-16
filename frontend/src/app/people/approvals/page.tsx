"use client";

import { PageHeader } from "@/components/ds/PageHeader";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { ApprovalsScreen } from "@/components/hr/leave/ApprovalsScreen";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";

// „Ludzie → Akceptacje” (16.10.2026): wnioski urlopowe zespołu do decyzji,
// historia i wpis nieobecności za pracownika. O dostępie decyduje serwer
// (przełożony swojego zespołu, Kadry i admin wszystkich; nikt siebie).
export default function PeopleApprovalsPage() {
  return (
    <HrConfigGate>
      {(config) => (
        <div className="space-y-4">
          <PageHeader
            title="Akceptacje"
            description="Wnioski Twojego zespołu do decyzji i historia nieobecności."
            density="compact"
          />
          <PeopleSectionNav config={config} active="approvals" />
          <ApprovalsScreen config={config} />
        </div>
      )}
    </HrConfigGate>
  );
}
