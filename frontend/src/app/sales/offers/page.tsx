"use client";

import { OffersView } from "@/components/sales/OffersView";
import { SalesShell } from "@/components/sales/SalesShell";

// Sprzedaż → Oferty: kroki po wysłanej ofercie i pozycje do decyzji.
export default function SalesOffersPage() {
  return (
    <SalesShell title="Sprzedaż" description="Oferty wysłane: co robisz dalej i które trzeba rozstrzygnąć.">
      <OffersView />
    </SalesShell>
  );
}
