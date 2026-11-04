import type { MetadataRoute } from "next";

/**
 * Wpisy mapy strony domeny kariery (etap 6 linków, decyzja D3 Artura
 * 20.10.2026): strona główna (tablica) i strony otwartych rekrutacji z listy
 * tablicy (`GET /api/public/career/jobs`). Zamknięta rekrutacja znika z listy,
 * więc i z mapy. Strony rekruterów nie trafiają — Google dojdzie do nich
 * z odnośników.
 */
export function careerSitemapEntries(
  host: string,
  jobSlugs: readonly string[],
): MetadataRoute.Sitemap {
  const origin = `https://${host}`;
  const unique = Array.from(new Set(jobSlugs.filter((s) => /^[a-z0-9-]+$/.test(s))));
  return [
    { url: `${origin}/`, changeFrequency: "daily", priority: 1 },
    ...unique.map((slug) => ({
      url: `${origin}/r/${slug}`,
      changeFrequency: "weekly" as const,
      priority: 0.8,
    })),
  ];
}

/** Slugi z odpowiedzi tablicy — odporne na brak trasy i inny kształt. */
export function boardJobSlugs(body: unknown): string[] {
  const jobs = (body as { jobs?: unknown } | null)?.jobs;
  if (!Array.isArray(jobs)) return [];
  return jobs
    .map((j) => (j as { slug?: unknown })?.slug)
    .filter((s): s is string => typeof s === "string");
}
