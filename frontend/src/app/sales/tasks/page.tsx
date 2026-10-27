"use client";

import { SalesShell } from "@/components/sales/SalesShell";
import { TasksView } from "@/components/sales/TasksView";

// Sprzedaż → Zadania handlowców (moje / zespołu).
export default function SalesTasksPage() {
  return (
    <SalesShell title="Sprzedaż" description="Zadania przy firmach i szansach.">
      <TasksView />
    </SalesShell>
  );
}
