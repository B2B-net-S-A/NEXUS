"use client";

import { useQuery } from "@tanstack/react-query";
import { kpisApi, type KpiResult } from "@/lib/api";

/**
 * Bieżący progres current_usera względem wszystkich KPI (dzień/tydzień/miesiąc).
 *
 * - `staleTime: 30s` — przy navigation między stronami nie przeładowujemy
 *   bez przerwy.
 * - `refetchInterval: 60s` — zapewnia świeżość nawet gdy WebSocket nie
 *   działa. Event-driven invalidation przychodzi z `useNotifications`
 *   (po kpi_nudge z backendu) i wywłaszczy to przez queryClient.
 * - Pusta lista dla ról nieoperacyjnych (admin / delivery_lead / user) —
 *   widget wtedy nie renderuje siebie.
 */
export function useMyKpis() {
  return useQuery<KpiResult[]>({
    queryKey: ["kpis", "me", "today"],
    queryFn: async () => {
      const { data } = await kpisApi.myToday();
      return data;
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });
}
