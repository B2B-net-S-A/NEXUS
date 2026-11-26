import { useQuery } from "@tanstack/react-query";

import { browserApiBase, type CareerBoardResponse } from "@/lib/career/api";
import { bigWord, facetCounts, fold, offerTags, type Facet } from "@/lib/career/site";

/*
 * Karta z tablicy (`GET /api/public/career/jobs`, publiczne, cache 60 s w API)
 * po slugu linku, a bez niego po tytule.
 */
export interface BoardPreview {
  /** Wielkie słowo (pierwsza plakietka). */
  word: string | null;
  /** Plakietki technologii nad tytułem grafiki (jak `offerTags` na stronie i w OG). */
  tags: string[];
  /** Miasta tablicy z liczbami — przygaszone kolumny na mapie grafiki. */
  facets: Facet[];
}

/**
 * Dane tablicy do podglądu grafiki posta (język A, 26.11.2026): słowo,
 * plakietki i miasta — to samo, z czego grafika OG strony kariery rysuje
 * technologie i mapę. Brak tablicy = podgląd bez plakietek i bez kolumn,
 * tak jak grafika, gdy tablica nie odpowiada.
 */
export function useBoardPreview(slug: string | null | undefined, title: string | null | undefined): BoardPreview {
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
  const card = bySlug ?? byTitle ?? null;
  const word = bigWord(card);
  return { word, tags: offerTags(word, card?.must ?? []), facets: facetCounts(jobs) };
}
