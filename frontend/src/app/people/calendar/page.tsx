"use client";

import { Suspense } from "react";

import { PageHeader } from "@/components/ds/PageHeader";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { TeamCalendar } from "@/components/hr/leave/TeamCalendar";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";

// „Ludzie → Kalendarz” (16.10.2026, filtry jak w Katalogu 22.10.2026): kto
// i kiedy jest nieobecny. Rodzaj nieobecności widzą tylko osoba, jej
// koordynator i Kadry (D6). `TeamCalendar` czyta zakres, filtr i okres z adresu.
export default function PeopleCalendarPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Ładowanie…</div>}>
      <HrConfigGate>
        {(config) => (
          <div className="space-y-4">
            <PageHeader
              title="Kalendarz"
              description="Nieobecności w zespole. Rodzaj widzą tylko osoba, jej koordynator i Kadry."
              density="compact"
            />
            <PeopleSectionNav config={config} active="calendar" />
            <TeamCalendar config={config} />
          </div>
        )}
      </HrConfigGate>
    </Suspense>
  );
}
