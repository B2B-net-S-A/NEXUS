"use client";

import { Suspense } from "react";

import { PageHeader } from "@/components/ds/PageHeader";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { ApprovalsScreen } from "@/components/hr/leave/ApprovalsScreen";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";

// „Ludzie → Akceptacje” (16.10.2026; jedna lista od 22.10.2026): nieobecności,
// raporty godzin i zgody do decyzji w jednej liście z chipami rodzaju,
// „Zdecydowane” z historią i wpis nieobecności za osobę. O dostępie decyduje
// serwer (koordynator swojego zespołu, Kadry i admin wszystkich; nikt siebie).
// `ApprovalsScreen` czyta z adresu chip, widok, miesiąc i osobę (linki
// z powiadomień: `?tab=consents&request=…`, `?kind=timesheet&year=&month=&user=`).
export default function PeopleApprovalsPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Ładowanie…</div>}>
      <HrConfigGate>
        {(config) => (
          <div className="space-y-4">
            <PageHeader
              title="Akceptacje"
              description="Nieobecności, raporty godzin i zgody do decyzji — w jednej liście."
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
