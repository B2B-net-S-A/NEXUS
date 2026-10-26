"use client";

import { Suspense } from "react";

import { CompaniesList } from "@/components/sales/CompaniesList";
import { SalesShell } from "@/components/sales/SalesShell";

// Sprzedaż → Firmy: kartoteka firm sprzedaży, osobna od Klientów (D2).
export default function SalesCompaniesPage() {
  return (
    <SalesShell title="Sprzedaż" description="Kartoteka firm — od leada do klienta.">
      <Suspense fallback={<p className="py-6 text-sm text-muted-foreground">Wczytywanie firm…</p>}>
        <CompaniesList />
      </Suspense>
    </SalesShell>
  );
}
