"use client";

import { Suspense } from "react";

import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { TrainingsScreen } from "@/components/trainings/TrainingsScreen";

// Szkolenia (decyzja Artura 13.11.2026, zamiast Akademii Compassa): biblioteka dla
// każdego, „Organizuję” dla TCM i Finansów, „Do podpisu” dla reprezentanta B2B.
export default function TrainingsPage() {
  return (
    <HrConfigGate>
      {() => (
        <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Ładowanie…</div>}>
          <TrainingsScreen />
        </Suspense>
      )}
    </HrConfigGate>
  );
}
