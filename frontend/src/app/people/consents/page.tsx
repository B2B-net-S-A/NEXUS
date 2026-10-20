"use client";

import { Suspense } from "react";

import { PageHeader } from "@/components/ds/PageHeader";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { MyConsentsScreen } from "@/components/hr/approvals/MyConsentsScreen";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";

// „Ludzie → Moje zgody” (20.10.2026): prośby o zgodę na wydatek albo premię
// poza umową i ich przebieg. Kto decyduje, liczy serwer; moduł „Zgody”
// (`approvals`) wyłączony = ekran pokazuje „Nie znaleziono” przez bramkę trasy.
export default function PeopleConsentsPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Ładowanie…</div>}>
      <HrConfigGate>
        {(config) => (
          <div className="space-y-4">
            <PageHeader
              title="Moje zgody"
              description="Wydatki i premie poza umową, o które prosisz — i kto o nich decyduje."
              density="compact"
            />
            <PeopleSectionNav config={config} active="consents" />
            {config.open_modules.approvals ? (
              <MyConsentsScreen />
            ) : (
              <p className="text-sm text-muted-foreground">Zgody ruszą po włączeniu modułu.</p>
            )}
          </div>
        )}
      </HrConfigGate>
    </Suspense>
  );
}
