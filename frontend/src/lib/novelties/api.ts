/**
 * Nowości do przeklikania — zapytania. Awaria = brak kropek i ✦ w pasku,
 * nigdy błąd na ekranie (to dodatek do pracy, nie jej warunek).
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { api } from "@/lib/api";
import type { Novelty, NoveltyEvent } from "./logic";

export const myNoveltiesKey = ["novelties", "mine"] as const;

export function useMyNovelties(enabled: boolean): Novelty[] {
  const query = useQuery({
    queryKey: myNoveltiesKey,
    queryFn: async () => (await api.get<Novelty[]>("/api/novelties/mine")).data,
    enabled,
    staleTime: 5 * 60_000,
    retry: 0,
  });
  return query.data ?? [];
}

/** Zapis zdarzenia; po zaliczeniu lista się odświeża (znika kropka i licznik). */
export function useNoveltyEvent(): (
  noveltyId: string,
  event: NoveltyEvent,
) => Promise<boolean> {
  const queryClient = useQueryClient();
  return useCallback(
    async (noveltyId: string, event: NoveltyEvent) => {
      try {
        await api.post(
          `/api/novelties/${encodeURIComponent(noveltyId)}/events`,
          { event },
        );
        if (event !== "seen")
          await queryClient.invalidateQueries({ queryKey: myNoveltiesKey });
        return true;
      } catch {
        return false;
      }
    },
    [queryClient],
  );
}

export type AdoptionState = "used" | "tour" | "dot" | "seen" | "untouched";

export interface AdoptionPerson {
  user_id: number;
  name: string;
  state: AdoptionState;
  completed_at: string | null;
  seen_count: number;
  reminded_at: string | null;
}

export interface NoveltyAdoption {
  id: string;
  title: string;
  tier: Novelty["tier"];
  shipped_on: string;
  pr: number | null;
  where: string;
  active: boolean;
  audience: number;
  counts: Record<AdoptionState, number>;
  people: AdoptionPerson[];
}

export const adoptionKey = ["novelties", "adoption"] as const;

/** Panel „kto już umie” — admin i Head of Recruitment (`HeadOfRecruitmentPlus`). */
export function useNoveltiesAdoption() {
  return useQuery({
    queryKey: adoptionKey,
    queryFn: async () =>
      (await api.get<NoveltyAdoption[]>("/api/novelties/adoption")).data,
  });
}

export async function remindNovelty(
  noveltyId: string,
  userIds: number[] | null,
): Promise<number> {
  const resp = await api.post<{ reminded: number }>(
    `/api/novelties/${encodeURIComponent(noveltyId)}/remind`,
    { user_ids: userIds },
  );
  return resp.data.reminded;
}
