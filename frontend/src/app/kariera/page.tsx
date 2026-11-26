import type { Metadata } from "next";

import { CareerBoard } from "@/components/career/site/CareerBoard";
import { SiteFrame } from "@/components/career/site/SiteFrame";
import { careerHref, primaryCareerHost } from "@/lib/career/host";
import { LIST_DESCRIPTION, OG_SITE_NAME, listOgTitle } from "@/lib/career/ogText";
import { fetchCareerBoard } from "@/lib/career/server";

import { careerRequestContext } from "./_context";

/**
 * Podgląd linku do listy (język A, tabela z makiety OG-w-portalach,
 * 26.11.2026): liczba otwartych rekrutacji w tytule, zdanie o projektach,
 * nazwa serwisu, adres i język jak na ofertach.
 */
export async function generateMetadata(): Promise<Metadata> {
  const board = await fetchCareerBoard();
  const title = listOgTitle(board.ok ? board.data.jobs.length : null);
  const url = `https://${primaryCareerHost()}/`;
  return {
    title: { absolute: title },
    description: LIST_DESCRIPTION,
    openGraph: { title, description: LIST_DESCRIPTION, url, siteName: OG_SITE_NAME, type: "website", locale: "pl_PL" },
    twitter: { card: "summary_large_image", title, description: LIST_DESCRIPTION },
  };
}

export const dynamic = "force-dynamic";

/**
 * Strona startowa hosta kariery: lista wszystkich otwartych rekrutacji
 * z opublikowanym opisem (etap 6, decyzja Artura D1 = A, 20.10.2026), od
 * 23.11.2026 w układzie nowej strony B2B Network (makieta KarieraA). Karta
 * prowadzi na link prowadzącego rekrutację (D2 = A); „Zostaw CV” idzie stałym
 * linkiem Head of Recruitment. Awaria API ma własny komunikat, nie pustą listę.
 */
export default async function CareerHome() {
  const [{ base }, result] = await Promise.all([careerRequestContext(), fetchCareerBoard()]);
  return (
    <SiteFrame homeHref={careerHref(base, { to: "home" })} rodoHref={careerHref(base, { to: "rodo" })}>
      <CareerBoard data={result.ok ? result.data : null} base={base} />
    </SiteFrame>
  );
}
