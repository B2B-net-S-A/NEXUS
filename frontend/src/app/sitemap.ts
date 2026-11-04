import type { MetadataRoute } from "next";
import { headers } from "next/headers";

import { serverApiBase } from "@/lib/career/api";
import { careerHosts, isCareerHost, primaryCareerHost, requestHost } from "@/lib/career/host";
import { boardJobSlugs, careerSitemapEntries } from "@/lib/career/sitemap";

/**
 * `sitemap.xml` zależny od hosta (etap 6 linków, decyzja D3 Artura 20.10.2026).
 * Domena kariery: tablica i otwarte rekrutacje. Host aplikacji: pusta mapa
 * (i tak `Disallow: /` w `app/robots.ts`). Awaria API = sama strona główna,
 * nigdy błąd mapy.
 */
export const dynamic = "force-dynamic";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  if (!isCareerHost(requestHost(await headers()), careerHosts())) return [];
  let slugs: string[] = [];
  try {
    const res = await fetch(`${serverApiBase()}/api/public/career/jobs`, {
      cache: "no-store",
    });
    if (res.ok) slugs = boardJobSlugs(await res.json());
  } catch {
    slugs = [];
  }
  return careerSitemapEntries(primaryCareerHost(), slugs);
}
