"use client";

// Start w NEXUSIE — twarda blokada (decyzja Artura 30.10.2026: wszyscy,
// obowiązkowo). Dopóki osoba nie przeklika najważniejszych funkcji swojej roli,
// każdy inny ekran przekierowuje na `/start`. Wyłącznik dla admina i HoR jest
// w panelu „Nowości — kto już umie”; awaria zapytania niczego nie blokuje.

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { useStartStatus } from "@/lib/novelties/api";
import { readTour, START_PATH, startAllows } from "@/lib/novelties/logic";
import { useAuthStore } from "@/store/auth";

/** `true` = ekranu nie pokazujemy, trwa przekierowanie na Start. */
export function useStartGate(): boolean {
  const user = useAuthStore((s) => s.user);
  const hydrated = useAuthStore((s) => s.hydrated);
  const pathname = usePathname() ?? "";
  const router = useRouter();
  const status = useStartStatus(
    hydrated && Boolean(user) && user?.role !== "trainee",
  );

  const touringStart = (() => {
    const tour = typeof window === "undefined" ? null : readTour();
    return Boolean(tour && status?.items.some((item) => item.id === tour.noveltyId));
  })();
  const blocked =
    Boolean(status?.enforced) && !startAllows(pathname, touringStart);

  useEffect(() => {
    if (blocked) router.replace(START_PATH);
  }, [blocked, router]);

  return blocked;
}
