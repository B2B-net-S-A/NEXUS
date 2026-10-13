"use client";

import { useQuery } from "@tanstack/react-query";
import { racesApi, type MyLeague } from "@/lib/insights-races-api";
import { WS_BACKED_SAFETY_POLL_MS } from "@/lib/polling";
import { hasSectionAccess } from "@/lib/section-access";
import { useAuthStore } from "@/store/auth";

export const MY_LEAGUE_QUERY_KEY = ["competitions", "my-league"] as const;

/**
 * Liga Mistrzów zalogowanej osoby — przycisk w górnym pasku.
 *
 * - Serwer trzyma ranking paska 5 min (jedno przeliczenie Ligi to ok. 3 s
 *   Postgresa, a pasek wisi na każdej stronie), więc częstsze pytanie
 *   i odświeżanie przy powrocie do karty nic by nie dało.
 * - Bez sekcji Insights zapytanie nie idzie wcale: trasa stoi za bramką
 *   Insights i odpowiedziałaby 403 co 5 minut.
 */
export function useMyLeague() {
  const user = useAuthStore((state) => state.user);
  return useQuery<MyLeague>({
    queryKey: MY_LEAGUE_QUERY_KEY,
    queryFn: racesApi.myLeague,
    staleTime: WS_BACKED_SAFETY_POLL_MS,
    refetchInterval: WS_BACKED_SAFETY_POLL_MS,
    refetchOnWindowFocus: false,
    enabled: hasSectionAccess(user, "insights"),
  });
}
