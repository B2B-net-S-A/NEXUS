/**
 * „Gdy Cię nie było” (16.11.2026): praca, która w czasie nieobecności poszła
 * do zastępcy, pokazana osobie po powrocie. Backend: `services/while_away.py`.
 */

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";

export interface WhileAwayAction {
  id: number;
  title: string;
  message: string;
  link: string | null;
  created_at: string;
  substitute_name: string;
  seen_by_substitute: boolean;
  handled_at: string | null;
  handled_by_name: string | null;
}

export interface WhileAwayGroup {
  label: string;
  count: number;
}

export interface WhileAwaySummary {
  since: string;
  until: string;
  substitute_names: string[];
  total: number;
  actions: WhileAwayAction[];
  others: WhileAwayGroup[];
}

export const WHILE_AWAY_QUERY_KEY = ["notifications", "while-away"] as const;

/** `null` z API = nic z nieobecności; inny kształt traktujemy tak samo. */
export function parseWhileAway(raw: unknown): WhileAwaySummary | null {
  if (raw == null || typeof raw !== "object") return null;
  const value = raw as Partial<WhileAwaySummary>;
  if (
    typeof value.since !== "string" ||
    typeof value.until !== "string" ||
    !Array.isArray(value.actions) ||
    !Array.isArray(value.others) ||
    !Array.isArray(value.substitute_names)
  ) {
    return null;
  }
  return value as WhileAwaySummary;
}

export function useWhileAway() {
  return useQuery({
    queryKey: WHILE_AWAY_QUERY_KEY,
    queryFn: async (): Promise<WhileAwaySummary | null> =>
      parseWhileAway((await api.get<unknown>("/api/notifications/while-away")).data),
    staleTime: 5 * 60_000,
  });
}

export async function markWhileAwayHandled(id: number): Promise<void> {
  await api.post(`/api/notifications/while-away/${id}/handled`);
}

export async function dismissWhileAway(): Promise<void> {
  await api.post("/api/notifications/while-away/dismiss");
}
