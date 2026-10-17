"use client";

import { Suspense } from "react";

import { CareScreen } from "@/components/care/CareScreen";

// „Ludzie w NEXUSIE” (16–17.10.2026): opieka nad konsultantami — „Ten tydzień”
// (domyślna), „Wszystkie kontrakty”, „Do przepięcia” i technologie z kart do
// przejrzenia. Zakładka w `?tab=`.
export default function CarePage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Ładowanie…</div>}>
      <CareScreen />
    </Suspense>
  );
}
