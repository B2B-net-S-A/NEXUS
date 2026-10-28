"use client";

import { ContactsDirectory } from "@/components/sales/mockups/ContactsDirectory";
import { SalesShell } from "@/components/sales/SalesShell";

// MAKIETA: Sprzedaż → Kontakty.
export default function SalesContactsPage() {
  return (
    <SalesShell title="Sprzedaż" description="Osoby we wszystkich firmach sprzedaży.">
      <ContactsDirectory />
    </SalesShell>
  );
}
