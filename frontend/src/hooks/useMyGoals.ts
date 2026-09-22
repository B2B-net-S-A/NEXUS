"use client";

import { useQuery } from "@tanstack/react-query";
import { kpisApi, type MyKpiGoals } from "@/lib/api";
import { WS_BACKED_SAFETY_POLL_MS } from "@/lib/polling";
import { hasSectionAccess } from "@/lib/section-access";
import { hasRole, useAuthStore } from "@/store/auth";

/**
 * Cele liderów (22.09.2026): Delivery Lead — hit ratio i placementy portfela
 * w kwartale, Head of Recruitment i TCM — cele zespołu (suma celów ludzi).
 *
 * Zapytanie idzie wyłącznie dla ról z celami lidera — widget wisi na każdej
 * stronie, a rekruterowi backend i tak odpowiada `kind: "none"`.
 */
export function useMyGoals() {
  const user = useAuthStore((state) => state.user);
  return useQuery<MyKpiGoals>({
    queryKey: ["kpis", "me", "goals"],
    queryFn: async () => {
      const { data } = await kpisApi.myGoals();
      return data;
    },
    staleTime: 60_000,
    refetchInterval: WS_BACKED_SAFETY_POLL_MS,
    refetchOnWindowFocus: true,
    enabled:
      hasSectionAccess(user, "insights") &&
      hasRole(user, "delivery_lead", "head_of_recruitment", "talent_community_manager"),
  });
}
