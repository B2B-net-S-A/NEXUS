import { useQuery } from "@tanstack/react-query";

import { browserApiBase, type CareerBoardResponse } from "@/lib/career/api";
import { bigWord, fold } from "@/lib/career/site";

/**
 * Wielkie słowo grafiki posta dla podglądu w oknie „Udostępnij” — to samo, co
 * narysuje grafika OG strony kariery: pierwsza krótka umiejętność z karty
 * tablicy (`GET /api/public/career/jobs`, publiczne, cache 60 s w API).
 * Karta po slugu linku, a bez niego po tytule. Brak tablicy = podgląd bez
 * słowa (tak jak grafika, gdy tablica nie odpowiada).
 */
export function useBoardWord(slug: string | null | undefined, title: string | null | undefined): string | null {
  const board = useQuery({
    queryKey: ["career-board-public"],
    queryFn: async (): Promise<CareerBoardResponse> => {
      const res = await fetch(`${browserApiBase()}/api/public/career/jobs`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return (await res.json()) as CareerBoardResponse;
    },
    staleTime: 60_000,
    retry: false,
  });
  const jobs = board.data?.jobs ?? [];
  const bySlug = slug ? jobs.find((j) => j.slug.toLowerCase() === slug.toLowerCase()) : undefined;
  const byTitle = title ? jobs.find((j) => fold(j.title.trim()) === fold(title.trim())) : undefined;
  return bigWord(bySlug ?? byTitle ?? null);
}
