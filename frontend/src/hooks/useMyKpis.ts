"use client";

import { useQuery } from "@tanstack/react-query";
import { kpisApi, type KpiResult } from "@/lib/api";
import { WS_BACKED_SAFETY_POLL_MS } from "@/lib/polling";

/**
 * Bieżący progres current_usera względem wszystkich KPI (dzień/tydzień/miesiąc).
 *
 * - `staleTime: 30s` — przy navigation między stronami nie przeładowujemy
 *   bez przerwy.
 * - `refetchInterval: 5 min` — siatka bezpieczeństwa, gdy WebSocket nie
 *   działa. Właściwe odświeżenie przychodzi z `useNotifications`
 *   (po kpi_nudge z backendu) przez queryClient. Widget wisi na KAŻDEJ
 *   stronie, więc co 60 s liczyło się jako stały ruch tła (patrz lib/polling).
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
    refetchInterval: WS_BACKED_SAFETY_POLL_MS,
    refetchOnWindowFocus: true,
  });
}
