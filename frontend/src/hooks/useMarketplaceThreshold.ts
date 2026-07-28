"use client";

/**
 * Efektywny próg alertowania targu — czytany z backendu, nie zgadywany.
 *
 * Dwa miejsca w UI obiecywały „alertujemy o dopasowaniach ze score ≥ 70",
 * podczas gdy `MARKETPLACE_SCORE_THRESHOLD` wynosił 80. Rekruter czytał
 * obietnicę, której system nie dotrzymywał, i nie miał jak tego zauważyć —
 * brak alertu wygląda identycznie jak brak dopasowań.
 *
 * Wartość zapasowa celowo równa się dzisiejszemu domyślnemu progowi backendu:
 * gdy `/marketplace/pool` jeszcze się nie wczytał, lepiej pokazać liczbę
 * prawdziwą niż optymistyczną.
 */

import { useQuery } from "@tanstack/react-query";

import { marketplaceApi } from "@/lib/api";

const FALLBACK_THRESHOLD = 80;

export function useMarketplaceThreshold(): number {
  const { data } = useQuery({
    queryKey: ["marketplace-pool-meta"],
    queryFn: () => marketplaceApi.getPool().then((r) => r.data),
    staleTime: 10 * 60_000,
  });
  return data?.score_threshold ?? FALLBACK_THRESHOLD;
}
