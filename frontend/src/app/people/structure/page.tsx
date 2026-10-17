"use client";

import { PageHeader } from "@/components/ds/PageHeader";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";
import { StructureScreen } from "@/components/hr/structure/StructureScreen";

// „Ludzie → Struktura” (etap 2, D4 i D7, 17.10.2026): kto komu podlega, piony
// firmy, zmiana przełożonego wielu osób naraz (od razu), rozjazd z Microsoft 365.
// Tylko Kadry i admin — serwer i tak broni trasy.
export default function PeopleStructurePage() {
  return (
    <HrConfigGate>
      {(config) => (
        <div className="space-y-4">
          <PageHeader
            title="Struktura"
            description="Piony, przełożeni i koordynatorzy. Zmiana działa od razu."
            density="compact"
          />
          <PeopleSectionNav config={config} active="structure" />
          <StructureScreen config={config} />
        </div>
      )}
    </HrConfigGate>
  );
}
