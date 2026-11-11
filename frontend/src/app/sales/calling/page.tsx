"use client";

import { CallingActions, CallQueueView } from "@/components/sales/calling/CallQueueView";
import { SalesShell } from "@/components/sales/SalesShell";

// Sprzedaż → Dzwonienie: kolejka kampanii i szans dzwoniącego (decyzje Artura 10.11.2026).
export default function SalesCallingPage() {
  return (
    <SalesShell
      title="Sprzedaż"
      description="Kolejka do dzwonienia. Wynik rozmowy to jedno kliknięcie, szansa powstaje dopiero z umówionego spotkania."
      actions={<CallingActions />}
    >
      <CallQueueView />
    </SalesShell>
  );
}
