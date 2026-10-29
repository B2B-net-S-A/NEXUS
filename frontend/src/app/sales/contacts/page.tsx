"use client";

import { Suspense } from "react";

import { ContactsDirectory } from "@/components/sales/ContactsDirectory";
import { SalesShell } from "@/components/sales/SalesShell";

// Sprzedaż → Kontakty: osoby ze wszystkich firm sprzedaży (audyt importu Atlasa 28.10.2026).
export default function SalesContactsPage() {
  return (
    <SalesShell title="Sprzedaż" description="Osoby we wszystkich firmach sprzedaży.">
      <Suspense fallback={<p className="py-6 text-sm text-muted-foreground">Wczytywanie kontaktów…</p>}>
        <ContactsDirectory />
      </Suspense>
    </SalesShell>
  );
}
