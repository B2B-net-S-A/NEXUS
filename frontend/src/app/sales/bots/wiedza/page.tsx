"use client";

import { KnowledgeBaseView } from "@/components/sales/potential/KnowledgeBaseView";
import { SalesShell } from "@/components/sales/SalesShell";

// Sprzedaż → Leady → Boty → Baza wiedzy: co ocena potencjału wie o nas
// (decyzja Artura z 23.11.2026, docs/claude/sprzedaz/ocena-potencjalu.md).
export default function SalesKnowledgeBasePage() {
  return (
    <SalesShell title="Sprzedaż" description="Co ocena potencjału wie o nas: oferta, gwarancje i referencje.">
      <KnowledgeBaseView />
    </SalesShell>
  );
}
