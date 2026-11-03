"use client";

import { Suspense } from "react";

import { CareScreen } from "@/components/care/CareScreen";

// Back office (moduł `back_office`, decyzja Artura 02.11.2026): ten sam ekran co
// `/care`, z kolejką zespołów jako główną zakładką. Stare linki `/care` działają.
export default function BackOfficePage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Ładowanie…</div>}>
      <CareScreen />
    </Suspense>
  );
}
