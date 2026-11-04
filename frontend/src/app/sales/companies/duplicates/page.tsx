"use client";

import { CompanyDuplicates } from "@/components/sales/CompanyDuplicates";
import { SalesShell } from "@/components/sales/SalesShell";

// Sprzedaż → Firmy → Duplikaty: ten sam NIP albo nazwa, scalanie (audyt importu 28.10.2026).
export default function SalesCompanyDuplicatesPage() {
  return (
    <SalesShell title="Duplikaty firm" description="Firmy z tym samym NIP-em albo tą samą nazwą.">
      <CompanyDuplicates />
    </SalesShell>
  );
}
