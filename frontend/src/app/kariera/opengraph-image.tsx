import { headers } from "next/headers";
import { ImageResponse } from "next/og";

import { OG_SIZE, ogFontsOrDefault } from "@/components/career/og";
import { OgListCard } from "@/components/career/ogMapCard";
import { requestDisplayHost } from "@/lib/career/host";
import { cityColumnsSvg } from "@/lib/career/mapSvg";
import { openRecruitmentsIT } from "@/lib/career/ogText";
import { buildCityMap, inCities, onMap } from "@/lib/career/polandMap";
import { fetchCareerBoard } from "@/lib/career/server";
import { facetCounts } from "@/lib/career/site";

export const size = OG_SIZE;
export const contentType = "image/png";
export const alt = "Otwarte rekrutacje IT — B2B Network";
export const dynamic = "force-dynamic";

/**
 * Grafika podglądu linku do listy ofert (język A, makieta OG-lista,
 * 26.11.2026): hasło, liczba otwartych rekrutacji i szklana mapa z kolumnami
 * miast z tablicy — te same liczby co na stronie. Awaria API = sama mapa
 * kraju bez kolumn i bez liczby, nigdy brak obrazka.
 */
export default async function Image() {
  const host = requestDisplayHost(await headers());
  const board = await fetchCareerBoard();
  const jobs = board.ok ? board.data.jobs : [];
  const facets = facetCounts(jobs);
  // Etykiety jak na mapie telefonu: cztery największe miasta, większe napisy.
  const map = buildCityMap(facets, { phone: true });
  const where = inCities(facets.filter((f) => onMap(f.label)).length);
  return new ImageResponse(
    (
      <OgListCard
        openLabel={jobs.length > 0 ? openRecruitmentsIT(jobs.length) : null}
        cityLine={`Zdalnie, hybrydowo i w biurze${where ? ` ${where}` : ""}`}
        map={cityColumnsSvg(map)}
        labels={map.labels}
        host={host}
      />
    ),
    { ...OG_SIZE, fonts: await ogFontsOrDefault() },
  );
}
