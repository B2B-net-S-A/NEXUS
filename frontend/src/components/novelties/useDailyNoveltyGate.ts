"use client";

// Poranna porcja nowości (decyzja Artura 18.11.2026). Dopóki osoba nie
// przeklika wszystkiego, co weszło do jej roli, każdy ekran przekierowuje na
// `/nowosci-dnia`. Najpierw Start w NEXUSIE i Poligon nowej osoby (porcja na
// nie czeka), na Poligonie ekrany są otwarte (tam idzie samo przeklikanie).
// Wyłącznik porcji jest w „Nowości — kto już umie”; awaria zapytania niczego
// nie blokuje. Decyzja: `dailyBlocks` w `lib/novelties/daily.ts`.

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { useDailyStatus, useStartStatus } from "@/lib/novelties/api";
import { DAILY_PATH, dailyBlocks } from "@/lib/novelties/daily";
import { readTour } from "@/lib/novelties/logic";
import { isPoligonActive } from "@/lib/poligon/mode";
import { isBoardOnly, useAuthStore } from "@/store/auth";

/** `true` = ekranu nie pokazujemy, trwa przekierowanie na porcję. */
export function useDailyNoveltyGate(): boolean {
  const user = useAuthStore((s) => s.user);
  const hydrated = useAuthStore((s) => s.hydrated);
  const pathname = usePathname() ?? "";
  const router = useRouter();
  const enabled = hydrated && Boolean(user) && user?.role !== "trainee";
  const status = useDailyStatus(enabled);
  // To samo zapytanie co `useStartGate` (wspólna pamięć react-query).
  const start = useStartStatus(enabled);

  const touringBatch = (() => {
    const tour = typeof window === "undefined" ? null : readTour();
    return Boolean(tour && status?.items.some((n) => n.id === tour.noveltyId));
  })();
  const blocked = dailyBlocks({
    dailyEnforced: Boolean(status?.enforced),
    start,
    poligon: isPoligonActive(),
    pathname,
    touringBatch,
    boardOnly: isBoardOnly(user),
  });

  useEffect(() => {
    if (blocked) router.replace(DAILY_PATH);
  }, [blocked, router]);

  return blocked;
}
