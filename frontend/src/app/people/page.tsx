"use client";

import { Suspense } from "react";

import { PageHeader } from "@/components/ds/PageHeader";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { PeopleDirectory } from "@/components/hr/people/PeopleDirectory";
import { PeopleHeaderActions } from "@/components/hr/people/PeopleHeaderActions";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";

// „Ludzie w NEXUSIE” (16.10.2026): katalog ludzi. Zakładki obszaru (kalendarz,
// akceptacje, sprawy, płace) — `PeopleSectionNav`. Od 22.10.2026 katalog ma
// widok „Schemat” (dawna „Struktura”, `?view=schemat`) i „Porządki” w nagłówku.
export default function PeoplePage() {
  return (
    <HrConfigGate>
      {(config) => (
        <div className="space-y-4">
          <PageHeader
            title="Ludzie"
            description="Kto z nami współpracuje, kto koordynuje i kto jest dziś dostępny."
            density="compact"
            actions={<PeopleHeaderActions config={config} />}
          />
          <PeopleSectionNav config={config} active="directory" />
          <Suspense fallback={<p className="py-6 text-sm text-muted-foreground">Wczytywanie ludzi…</p>}>
            <PeopleDirectory config={config} />
          </Suspense>
        </div>
      )}
    </HrConfigGate>
  );
}
