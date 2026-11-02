"use client";

import { OffersView } from "@/components/sales/OffersView";
import { SalesShell } from "@/components/sales/SalesShell";

// Sprzedaż → Oferty: szanse z wysłaną ofertą.
export default function SalesOffersPage() {
  return (
    <SalesShell title="Sprzedaż" description="Szanse z wysłaną ofertą.">
      <OffersView />
    </SalesShell>
  );
}
