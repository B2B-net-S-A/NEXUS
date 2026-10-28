"use client";

import { SalesSummary } from "@/components/sales/mockups/SalesSummary";
import { SalesShell } from "@/components/sales/SalesShell";

// MAKIETA: Sprzedaż → Podsumowanie.
export default function SalesSummaryPage() {
  return (
    <SalesShell title="Sprzedaż" description="Lejek zespołu i szanse bez ruchu.">
      <SalesSummary />
    </SalesShell>
  );
}
