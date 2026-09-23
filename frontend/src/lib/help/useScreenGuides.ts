/**
 * Przewodniki ekranów (`GET /api/help/screens`) — pobierane raz na sesję.
 * Awaria = brak dymków i przycisku „?”, nigdy błąd na ekranie.
 */

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ScreenGuide } from "@/lib/jarvis/types";

export const screenGuidesKey = ["help-screens"] as const;

export async function fetchScreenGuides(): Promise<ScreenGuide[]> {
  return (await api.get<ScreenGuide[]>("/api/help/screens")).data;
}

export function useScreenGuides(enabled: boolean): Map<string, ScreenGuide> {
  const query = useQuery({
    queryKey: screenGuidesKey,
    queryFn: fetchScreenGuides,
    enabled,
    staleTime: Infinity,
    retry: 0,
  });
  const map = new Map<string, ScreenGuide>();
  for (const guide of query.data ?? []) map.set(guide.key, guide);
  return map;
}
