"use client";

import { useEffect, useState } from "react";

/**
 * Stan zsynchronizowany z parametrem adresu. Efekt zależy od WARTOŚCI
 * parametru, a nie od tożsamości `searchParams`: miękka nawigacja App Routera
 * (klik w powiadomienie na tej samej stronie) zmienia adres bez odmontowania
 * strony, a inicjalizator `useState` odpala się raz. `null` z adresu NIE
 * cofa ręcznego wyboru — parametr, który zniknął, to nie polecenie.
 */
export function useUrlSyncedState<T extends string>(fromUrl: T | null, fallback: T | null) {
  const [value, setValue] = useState<T | null>(fromUrl ?? fallback);
  useEffect(() => {
    if (fromUrl !== null) setValue(fromUrl);
  }, [fromUrl]);
  return [value, setValue] as const;
}

/** Podmienia parametry bieżącego adresu bez dokładania wpisu w historii. */
export function writeUrlParams(patch: Record<string, string | null>) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  for (const [name, value] of Object.entries(patch)) {
    if (value == null) url.searchParams.delete(name);
    else url.searchParams.set(name, value);
  }
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next !== current) window.history.replaceState(window.history.state, "", next);
}
