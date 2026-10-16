"use client";

import { useEffect, useState } from "react";

import type { YearMonth } from "./time-format";

/**
 * Miesiąc sterowany adresem (link z powiadomienia), nadal przełączalny strzałkami.
 * Efekt zależy od WARTOŚCI „rok-miesiąc”: miękka nawigacja App Routera zmienia adres
 * bez odmontowania ekranu, więc sam inicjalizator `useState` zostałby przy starym
 * miesiącu (wzorzec `useUrlSyncedState` z `lib/url-selection.ts`).
 */
export function useUrlMonth(fromUrl: YearMonth | undefined, fallback: () => YearMonth) {
  const urlKey = fromUrl ? `${fromUrl.year}-${fromUrl.month}` : null;
  const [period, setPeriod] = useState<YearMonth>(() => fromUrl ?? fallback());
  useEffect(() => {
    if (urlKey === null) return;
    const [year, month] = urlKey.split("-").map(Number);
    setPeriod({ year, month });
  }, [urlKey]);
  return [period, setPeriod] as const;
}
