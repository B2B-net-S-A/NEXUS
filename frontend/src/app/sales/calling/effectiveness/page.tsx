"use client";

import { CallingModeSwitch } from "@/components/sales/calling/CallingModeSwitch";
import { EffectivenessView } from "@/components/sales/calling/EffectivenessView";
import { SalesShell } from "@/components/sales/SalesShell";

// Sprzedaż → Dzwonienie → Skuteczność (decyzje Artura 11.11.2026). O dostępie decyduje
// backend: trasa wymaga „Sprzedaż: edycja”, bez niego ekran pokazuje 403 z nazwą uprawnienia.
export default function SalesCallingEffectivenessPage() {
  return (
    <SalesShell
      title="Sprzedaż"
      description="Co daje dzwonienie: kampanie, listy, pory dnia, oferta ogólna, spotkania i osoby."
      actions={<CallingModeSwitch />}
    >
      <EffectivenessView />
    </SalesShell>
  );
}
