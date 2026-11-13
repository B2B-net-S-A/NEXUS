"use client";

import { Suspense } from "react";

import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { NewTrainingScreen } from "@/components/trainings/NewTrainingScreen";

// Nowe szkolenie: zamówienie dla trenera z umową albo pracownika (TCM, admin).
export default function NewTrainingPage() {
  return (
    <HrConfigGate>
      {() => (
        <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Ładowanie…</div>}>
          <NewTrainingScreen />
        </Suspense>
      )}
    </HrConfigGate>
  );
}
