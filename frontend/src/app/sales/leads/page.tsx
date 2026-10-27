"use client";

import { LeadsView } from "@/components/sales/LeadsView";
import { SalesShell } from "@/components/sales/SalesShell";

// Sprzedaż → Leady (makieta M4): import z Atlasa i wpisy ręczne.
export default function SalesLeadsPage() {
  return (
    <SalesShell title="Sprzedaż" description="Sygnały, że firma może kupić — zanim staną się szansą.">
      <LeadsView />
    </SalesShell>
  );
}
