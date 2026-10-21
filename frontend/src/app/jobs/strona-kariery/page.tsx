"use client";

import { CareerQueue } from "@/components/v2/job-ad/CareerQueue";

/**
 * Rekrutacje → „Strona kariery do uzupełnienia” (21.10.2026): otwarte
 * rekrutacje bez strony kariery, „Opublikuj i następna”. Bramka jak
 * „Rekrutacje” (sekcja Pipeline); API odmawia rolom bez prawa publikacji.
 */
export default function CareerQueuePage() {
  return (
    <div className="mx-auto max-w-[1440px] space-y-4 p-4 md:p-6">
      <div>
        <p className="text-sm text-muted-foreground">Rekrutacje</p>
        <h1 className="text-2xl font-bold tracking-[-0.02em] text-foreground">
          Strona kariery do uzupełnienia
        </h1>
        <p className="mt-1 max-w-4xl text-sm text-muted-foreground">
          Otwarte rekrutacje, które nie wiszą jeszcze na kariera.b2bnetwork.pl. Treść jest
          przygotowana z Profilu Championa — przeczytaj ją i kliknij „Opublikuj i następna”.
        </p>
      </div>
      <CareerQueue />
    </div>
  );
}
