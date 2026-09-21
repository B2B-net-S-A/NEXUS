"use client";

import { Suspense } from "react";

import { CalendarCycleScreen } from "@/components/calendar/cycle/CalendarCycleScreen";

/**
 * `/calendar` — „Rozmowy u klienta” (0338).
 *
 * Do 09.2026 była tu wyłącznie siatka tygodnia, czyli kopia Outlooka trzech
 * osób (10 wydarzeń założonych w NEXUSIE w całej historii). Teraz ekran
 * prowadzi cykl rozmowy kandydata u klienta; siatka została zakładką „Tydzień”.
 */
export default function CalendarPage() {
  // `useSearchParams` wymaga granicy Suspense na prerenderze.
  return (
    <Suspense
      fallback={<div className="p-8 text-sm text-muted-foreground">Ładowanie kalendarza...</div>}
    >
      <CalendarCycleScreen />
    </Suspense>
  );
}
