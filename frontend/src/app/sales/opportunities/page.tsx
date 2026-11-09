"use client";

import { Suspense } from "react";

import { OpportunitiesView } from "@/components/sales/OpportunitiesView";
import { SalesShell } from "@/components/sales/SalesShell";

// Tablica i lista szans; `/sales` prowadzi od 09.11.2026 do „Mojego dnia”.
export default function SalesOpportunitiesPage() {
  return (
    <SalesShell title="Sprzedaż" description="Szanse w lejku, firmy i kogo w nich znamy.">
      <Suspense fallback={<p className="py-6 text-sm text-muted-foreground">Wczytywanie szans…</p>}>
        <OpportunitiesView />
      </Suspense>
    </SalesShell>
  );
}
