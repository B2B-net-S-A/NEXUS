"use client";

import { SalesShell } from "@/components/sales/SalesShell";
import { TendersView } from "@/components/sales/tenders/TendersView";

// Sprzedaż → Leady → Przetargi: BZP i TED po regułach Kingi (decyzja Artura 24.11.2026).
export default function SalesTendersPage() {
  return (
    <SalesShell title="Sprzedaż" description="Przetargi z BZP i TED, przesiane regułami.">
      <TendersView />
    </SalesShell>
  );
}
