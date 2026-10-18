"use client";

import { Suspense } from "react";

import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { MyTimeScreen } from "@/components/hr/MyTimeScreen";

// `MyTimeScreen` czyta zakładkę i miesiąc z adresu (linki z powiadomień).
export default function MyTimePage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Ładowanie…</div>}>
      <HrConfigGate>{(config) => <MyTimeScreen config={config} />}</HrConfigGate>
    </Suspense>
  );
}
