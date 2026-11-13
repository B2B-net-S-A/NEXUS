"use client";

import { LegalMonitoringMockup } from "@/components/legal-monitoring/LegalMonitoringMockup";
import { PageHeader } from "@/components/ds/PageHeader";

// MAKIETA (13.11.2026): ekran czyta pozycje z pliku lokalnego, bez API.
// Docelowo strona stoi za uprawnieniem „Monitoring prawny” (RequirePermission).
export default function LegalMonitoringPage() {
  return (
    <div className="mx-auto max-w-6xl space-y-4 p-4 md:p-6">
      <PageHeader
        title="Monitoring prawny"
        description="Orzeczenia, interpretacje i zmiany prawa o B2B, estońskim CIT i ZUS. Automat dopisuje pozycje w dni robocze rano."
        density="compact"
      />
      <LegalMonitoringMockup />
    </div>
  );
}
