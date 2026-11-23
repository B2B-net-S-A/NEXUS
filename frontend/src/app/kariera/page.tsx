import type { Metadata } from "next";

import { CareerBoard } from "@/components/career/site/CareerBoard";
import { SiteFrame } from "@/components/career/site/SiteFrame";
import { careerHref } from "@/lib/career/host";
import { fetchCareerBoard } from "@/lib/career/server";

import { careerRequestContext } from "./_context";

export const metadata: Metadata = { title: "Kariera" };

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
