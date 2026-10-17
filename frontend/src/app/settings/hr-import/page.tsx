"use client";

import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { HrImportHistory } from "@/components/hr/settings/HrImportHistory";
import { HrImportPanel } from "@/components/hr/settings/HrImportPanel";

// Ustawienia → Zespół i dostęp → Import z Compassa („Ludzie w NEXUSIE”).
// Na sucho sprawdzają Kadry i administrator, zapisuje wyłącznie administrator;
// o dostępie i tak decyduje serwer (`/api/hr/admin/import`).
export default function HrImportPage() {
  return (
    <HrConfigGate>
      {(config) =>
        config.me.people_admin || config.me.is_admin ? (
          <div className="mx-auto max-w-7xl space-y-4">
            <PageHeader
              density="compact"
              title="Import z Compassa"
              description="Paczka eksportu → sprawdzenie na sucho → zapis wybranych modułów. Drugi zapis tej samej paczki niczego nie zmienia."
            />
            <HrImportPanel isAdmin={config.me.is_admin} />
            <HrImportHistory />
          </div>
        ) : (
          <QueryStateNotice
            state="forbidden"
            description="Import z Compassa sprawdza osoba z uprawnieniem „Kadry”, a zapisuje administrator."
          />
        )
      }
    </HrConfigGate>
  );
}
