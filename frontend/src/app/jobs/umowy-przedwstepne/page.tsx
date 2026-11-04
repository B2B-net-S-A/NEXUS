"use client";

import { Suspense } from "react";

import { PreContractsList } from "@/components/v2/recruitment/PreContractsList";

/**
 * Rekrutacje → „Umowy przedwstępne” (0506, 21.10.2026): prośby o umowę
 * przedwstępną przy osobach w rekrutacjach — stan, kto wystawia, ważność,
 * termin umowy B2B i decyzje o karze. Bramka jak „Rekrutacje” (sekcja
 * Pipeline); zakres wierszy liczy API.
 */
export default function PreContractsPage() {
  return (
    <div className="mx-auto max-w-[1440px] space-y-4 p-4 md:p-6">
      <div>
        <p className="text-sm text-muted-foreground">Rekrutacje</p>
        <h1 className="text-2xl font-bold tracking-[-0.02em] text-foreground">Umowy przedwstępne</h1>
        <p className="mt-1 max-w-4xl text-sm text-muted-foreground">
          Prośby o umowę przedwstępną przy osobach w rekrutacjach: kto prosił, kto wystawia, czy
          kandydat i firma podpisali i do kiedy umowa obowiązuje.
        </p>
      </div>
      <Suspense fallback={null}>
        <PreContractsList />
      </Suspense>
    </div>
  );
}
