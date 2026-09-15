"use client";

import { useQuery } from "@tanstack/react-query";
import { kpisApi, type KpiResult } from "@/lib/api";
import { WS_BACKED_SAFETY_POLL_MS } from "@/lib/polling";
import { hasSectionAccess } from "@/lib/section-access";
import { useAuthStore } from "@/store/auth";

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
 * - Bez sekcji Insights zapytanie nie idzie wcale: backend odpowiada wtedy 403
 *   (F02, audyt 14.09.2026), a widget wisi na każdej stronie — co 5 min
 *   byłby to kolejny odrzucony request w konsoli.
 */
export function useMyKpis() {
  const user = useAuthStore((state) => state.user);
  return useQuery<KpiResult[]>({
    queryKey: ["kpis", "me", "today"],
    queryFn: async () => {
      const { data } = await kpisApi.myToday();
      return data;
    },
    staleTime: 30_000,
    refetchInterval: WS_BACKED_SAFETY_POLL_MS,
    refetchOnWindowFocus: true,
    enabled: hasSectionAccess(user, "insights"),
  });
}
