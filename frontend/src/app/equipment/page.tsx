"use client";

import { Suspense } from "react";

import { EquipmentScreen } from "@/components/equipment/EquipmentScreen";
import { HrConfigGate } from "@/components/hr/HrConfigGate";

// „Ludzie w NEXUSIE” — Sprzęt i protokoły recepcji (kroki S1–S3).
export default function EquipmentPage() {
  return (
    <HrConfigGate>
      {(config) => (
        <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Ładowanie…</div>}>
          <EquipmentScreen config={config} />
        </Suspense>
      )}
    </HrConfigGate>
  );
}
