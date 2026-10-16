"use client";

import { PageHeader } from "@/components/ds/PageHeader";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { PeopleDirectory } from "@/components/hr/people/PeopleDirectory";

// „Ludzie w NEXUSIE” (16.10.2026): katalog ludzi. Kolejne zakładki
// (kalendarz, akceptacje, płace, sprawy) dochodzą z modułami.
export default function PeoplePage() {
  return (
    <HrConfigGate>
      {(config) => (
        <div className="space-y-4">
          <PageHeader
            title="Ludzie"
            description="Kto u nas pracuje, komu podlega i gdzie domyślnie pracuje."
            density="compact"
          />
          <PeopleDirectory config={config} />
        </div>
      )}
    </HrConfigGate>
  );
}
