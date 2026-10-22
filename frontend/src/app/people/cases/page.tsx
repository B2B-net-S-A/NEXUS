"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { CasesBoard } from "@/components/admin-cases/CasesBoard";
import { PageHeader } from "@/components/ds/PageHeader";
import { HrConfigGate } from "@/components/hr/HrConfigGate";

function RedirectToCare() {
  const router = useRouter();
  useEffect(() => {
    // „Do zrobienia” to domyślna zakładka Opieki.
    router.replace("/care");
  }, [router]);
  return <p className="py-6 text-sm text-muted-foreground">Przenoszenie do Opieki…</p>;
}

// „Ludzie w NEXUSIE” (E6): sprawy skrzynki administracja@. Zakładka „Sprawy”
// przeszła z „Ludzi” do „Opieki” (decyzja Artura 22.10.2026) — stare linki
// i zakładki przeglądarki prowadzą na tablicę „Do zrobienia”. Przy module opieki
// wyłączonym tablica zostaje tutaj, żeby sprawy nie zniknęły.
export default function PeopleCasesPage() {
  return (
    <HrConfigGate>
      {(config) =>
        config.open_modules.care ? (
          <RedirectToCare />
        ) : (
          <div className="space-y-4">
            <PageHeader
              title="Sprawy administracja@"
              description="Maile ze skrzynki, nowe kontrakty i odejścia zakładają sprawy same."
              density="compact"
            />
            <CasesBoard config={config} />
          </div>
        )
      }
    </HrConfigGate>
  );
}
