"use client";

import { MeetingsView } from "@/components/sales/MeetingsView";
import { SalesShell } from "@/components/sales/SalesShell";

// Sprzedaż → Spotkania handlowców.
export default function SalesMeetingsPage() {
  return (
    <SalesShell title="Sprzedaż" description="Spotkania przy firmach i szansach.">
      <MeetingsView />
    </SalesShell>
  );
}
