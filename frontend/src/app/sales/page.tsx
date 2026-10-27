"use client";

import { Suspense } from "react";

import { OpportunitiesView } from "@/components/sales/OpportunitiesView";
import { SalesShell } from "@/components/sales/SalesShell";

// Sprzedaż (Atlas → NEXUS, 26.10.2026): tablica i lista szans (makieta M2).
export default function SalesPage() {
  return (
    <SalesShell title="Sprzedaż" description="Szanse w lejku, firmy i kogo w nich znamy.">
      <Suspense fallback={<p className="py-6 text-sm text-muted-foreground">Wczytywanie szans…</p>}>
        <OpportunitiesView />
      </Suspense>
    </SalesShell>
  );
}
