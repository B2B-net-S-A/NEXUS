"use client";

import { PageHeader } from "@/components/ds/PageHeader";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { PeopleDirectory } from "@/components/hr/people/PeopleDirectory";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";

// „Ludzie w NEXUSIE” (16.10.2026): katalog ludzi. Zakładki obszaru (kalendarz,
// akceptacje, sprawy, płace) — `PeopleSectionNav`.
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
          <PeopleSectionNav config={config} active="directory" />
          <PeopleDirectory config={config} />
        </div>
      )}
    </HrConfigGate>
  );
}
