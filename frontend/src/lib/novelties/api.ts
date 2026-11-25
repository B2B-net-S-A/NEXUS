/**
 * Nowości do przeklikania — zapytania. Awaria = brak porcji i archiwum ✦,
 * nigdy błąd na ekranie ani blokada (to dodatek do pracy, nie jej warunek).
 */

import { type QueryClient, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { Lesson } from "./lessons";
import type { DailyStatus, LukiMatrix, Novelty, NoveltyEvent, StartStatus } from "./logic";

export const myNoveltiesKey = ["novelties", "mine"] as const;

export function useMyNovelties(enabled: boolean): Novelty[] {
  return useMyNoveltiesState(enabled).items;
}

/** Lista z `/mine` i to, czy już przyszła (pusta lista ≠ jeszcze nie wiadomo). */
export function useMyNoveltiesState(enabled: boolean): { items: Novelty[]; loaded: boolean } {
  const query = useQuery({
    queryKey: myNoveltiesKey,
    queryFn: async () => (await api.get<Novelty[]>("/api/novelties/mine")).data,
    enabled,
    staleTime: 5 * 60_000,
    retry: 0,
  });
  return { items: query.data ?? [], loaded: query.isSuccess };
}

/** Zapis zdarzenia; po zaliczeniu odświeżają się lista, porcja i Start. */
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
        if (event !== "seen") {
          await queryClient.invalidateQueries({ queryKey: myNoveltiesKey });
          await queryClient.invalidateQueries({ queryKey: startKey });
          await queryClient.invalidateQueries({ queryKey: dailyKey });
        }
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
  /** Przeklikanie „Start w NEXUSIE” (bez terminu, obowiązkowe). */
  start: boolean;
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

export const startKey = ["novelties", "start"] as const;

/**
 * Start w NEXUSIE osoby. Awaria zapytania = brak blokady: Start ma uczyć,
 * a nie zamykać ludziom NEXUS, gdy coś nie odpowie. Dane dopiero po
 * zamontowaniu: z pamięci zapytań są w kliencie od pierwszego renderu,
 * a serwer renderuje bez nich (błąd hydracji w powłoce i w panelu).
 */
export function useStartStatus(enabled: boolean): StartStatus | null {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const query = useQuery({
    queryKey: startKey,
    queryFn: async () => (await api.get<StartStatus>("/api/novelties/start")).data,
    enabled,
    staleTime: 60_000,
  });
  return mounted ? (query.data ?? null) : null;
}

/**
 * Świeży stan Startu do decyzji „dokąd teraz” (po onboardingu). Wpisuje się
 * w pamięć `useStartGate`, więc bramka na następnym ekranie nie czeka na drugie
 * zapytanie. Awaria = `null` (brak blokady, jak w `useStartStatus`).
 */
export async function fetchStartStatus(queryClient: QueryClient): Promise<StartStatus | null> {
  try {
    return await queryClient.fetchQuery({
      queryKey: startKey,
      queryFn: async () => (await api.get<StartStatus>("/api/novelties/start")).data,
      staleTime: 0,
    });
  } catch {
    return null;
  }
}

/** Wyłącznik blokady Startu dla całej firmy (admin, Head of Recruitment). */
export async function setStartGate(enforced: boolean): Promise<boolean> {
  const resp = await api.put<{ enforced: boolean }>("/api/novelties/start/gate", {
    enforced,
  });
  return resp.data.enforced;
}

/** Wyłącznik blokady Poligonu nowych osób (admin, HoR). Start zostaje, jak był. */
export async function setPoligonGate(on: boolean): Promise<boolean> {
  const resp = await api.put<{ poligon: boolean }>("/api/novelties/start/gate", {
    poligon: on,
  });
  return resp.data.poligon;
}

export const dailyKey = ["novelties", "daily"] as const;

/**
 * Poranna porcja nowości (18.11.2026). Jak przy Starcie: dane dopiero po
 * zamontowaniu, a awaria zapytania = brak blokady.
 */
export function useDailyStatus(enabled: boolean): DailyStatus | null {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const query = useQuery({
    queryKey: dailyKey,
    queryFn: async () => (await api.get<DailyStatus>("/api/novelties/daily")).data,
    enabled,
    staleTime: 60_000,
    // Odłożona porcja wraca o wybranej godzinie bez przeładowania strony.
    refetchInterval: (q) => (q.state.data?.postponed_until ? 60_000 : false),
    retry: 0,
  });
  return mounted ? (query.data ?? null) : null;
}

export const lessonsKey = ["novelties", "lessons"] as const;

/** Szkolenia → „Nowości w NEXUSIE”: lekcje z roli osoby, bez terminu ważności. */
export function useMyLessons() {
  return useQuery({
    queryKey: lessonsKey,
    queryFn: async () => (await api.get<Lesson[]>("/api/novelties/lessons")).data,
    staleTime: 60_000,
  });
}

export type LessonEvent =
  | "shown"
  | "solo_failed"
  | "solo_passed"
  | "quiz_wrong"
  | "restart"
  | "completed"
  | "review_passed"
  | "review_failed"
  /** „Coś nie działa — zalicz mimo to” (Artur, 25.11.2026): zalicza lekcję z każdego etapu. */
  | "broken";

/** Etap lekcji. Błąd zapisu nie zatrzymuje osoby — wraca jako `false`. */
export async function sendLessonEvent(lessonId: string, event: LessonEvent): Promise<boolean> {
  try {
    await api.post(`/api/novelties/lessons/${encodeURIComponent(lessonId)}/events`, { event });
    return true;
  } catch {
    return false;
  }
}

/** Odłożenie porcji dnia (raz dziennie, najpóźniej do 15:00). */
export async function postponeDaily(option: string): Promise<string> {
  const resp = await api.post<{ postponed_until: string }>("/api/novelties/daily/postpone", { option });
  return resp.data.postponed_until;
}

/** Pominięcie porcji dnia — tylko admin. */
export async function skipDaily(): Promise<void> {
  await api.post("/api/novelties/daily/skip");
}

/** Wyłącznik porannej porcji nowości dla całej firmy (admin, HoR). */
export async function setDailyGate(on: boolean): Promise<boolean> {
  const resp = await api.put<{ daily: boolean }>("/api/novelties/start/gate", {
    daily: on,
  });
  return resp.data.daily;
}

export const lukiKey = ["novelties", "poligon-luki"] as const;

/** „Kto zna NEXUS”: macierz rekruterzy × funkcje (admin, HoR). */
export function usePoligonLuki(enabled = true) {
  return useQuery({
    queryKey: lukiKey,
    queryFn: async () => (await api.get<LukiMatrix>("/api/novelties/poligon/luki")).data,
    enabled,
    staleTime: 5 * 60_000,
  });
}

/** Wysyła poligon z lukami: zalicza ćwiczenia z pracy i ustawia termin. */
export async function sendPoligonLuki(due?: string): Promise<{ due: string; people: number; credited: number }> {
  const resp = await api.post<{ due: string; people: number; credited: number }>(
    "/api/novelties/poligon/luki",
    due ? { due } : {},
  );
  return resp.data;
}
