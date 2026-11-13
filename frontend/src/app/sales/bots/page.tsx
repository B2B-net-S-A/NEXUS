"use client";

import { BotsView } from "@/components/sales/bots/BotsView";
import { SalesShell } from "@/components/sales/SalesShell";

// Sprzedaż → Leady → Boty: cztery boty Sprzedaży (decyzja Artura z 13.11.2026).
export default function SalesBotsPage() {
  return (
    <SalesShell title="Sprzedaż" description="Boty, które szukają okazji, robią research i uzupełniają dane.">
      <BotsView />
    </SalesShell>
  );
}
