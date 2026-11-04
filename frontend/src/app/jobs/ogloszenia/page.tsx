"use client";

import { MissingAdsQueue } from "@/components/v2/job-ad/MissingAdsQueue";

/**
 * Rekrutacje → „Ogłoszenia do nadrobienia” (27.10.2026): tu prowadzi
 * zbiorczy mail o brakujących ogłoszeniach. Bramka jak „Rekrutacje” (sekcja
 * Pipeline); API odmawia rolom bez prawa publikacji.
 */
export default function MissingAdsPage() {
  return (
    <div className="mx-auto max-w-[1440px] space-y-4 p-4 md:p-6">
      <div>
        <p className="text-sm text-muted-foreground">Rekrutacje</p>
        <h1 className="text-2xl font-bold tracking-[-0.02em] text-foreground">
          Ogłoszenia do nadrobienia
        </h1>
        <p className="mt-1 max-w-4xl text-sm text-muted-foreground">
          Otwarte rekrutacje bez strony kariery, Pracuj.pl albo JustJoin.IT. Otwórz okno
          ogłoszenia, wstaw je i wklej link — przypomnienia o tym kanale przestaną przychodzić.
        </p>
      </div>
      <MissingAdsQueue />
    </div>
  );
}
