"use client";

import { MyDayView } from "@/components/sales/MyDayView";
import { SalesShell } from "@/components/sales/SalesShell";

export default function SalesMyDayPage() {
  return (
    <SalesShell title="Sprzedaż">
      <MyDayView />
    </SalesShell>
  );
}
