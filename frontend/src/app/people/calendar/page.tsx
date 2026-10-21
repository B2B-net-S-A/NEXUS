"use client";

import { PageHeader } from "@/components/ds/PageHeader";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { TeamCalendar } from "@/components/hr/leave/TeamCalendar";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";

// „Ludzie → Kalendarz zespołu” (16.10.2026): kto i kiedy jest nieobecny.
// Rodzaj nieobecności widzą tylko osoba, jej przełożony i Kadry (D6).
export default function PeopleCalendarPage() {
  return (
    <HrConfigGate>
      {(config) => (
        <div className="space-y-4">
          <PageHeader
            title="Kalendarz zespołu"
            description="Nieobecności w miesiącu. Rodzaj widzą tylko osoba, jej koordynator i Kadry."
            density="compact"
          />
          <PeopleSectionNav config={config} active="calendar" />
          <TeamCalendar config={config} />
        </div>
      )}
    </HrConfigGate>
  );
}
