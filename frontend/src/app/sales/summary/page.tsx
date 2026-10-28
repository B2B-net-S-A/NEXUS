"use client";

import { SalesSummary } from "@/components/sales/SalesSummary";
import { SalesShell } from "@/components/sales/SalesShell";

// Sprzedaż → Podsumowanie: lejek zespołu zamiast pulpitu Atlasa (audyt importu 28.10.2026).
export default function SalesSummaryPage() {
  return (
    <SalesShell title="Sprzedaż" description="Lejek zespołu i szanse bez ruchu.">
      <SalesSummary />
    </SalesShell>
  );
}
