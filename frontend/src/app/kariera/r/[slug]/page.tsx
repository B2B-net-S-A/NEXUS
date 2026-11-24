import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { OfferPage } from "@/components/career/site/OfferPage";
import { fetchCareerBoard, fetchCareerJob } from "@/lib/career/server";
import { paramsSummary } from "@/lib/career/format";
import { primaryCareerHost } from "@/lib/career/host";
import { jobPostingJsonLd, jsonLdString } from "@/lib/career/jobPosting";

import { careerRequestContext } from "../../_context";

interface PageProps {
  params: Promise<{ slug: string }>;
}

export const dynamic = "force-dynamic";

/** Nieznany slug albo niezatwierdzony profil → 404; inna awaria → błąd strony. */
async function load(slug: string) {
  const result = await fetchCareerJob(slug.toLowerCase());
  if (!result.ok) {
    if (result.notFound) notFound();
    throw new Error("Nie udało się wczytać rekrutacji.");
  }
  return result.data;
}

function canonicalUrl(slug: string): string {
  return `https://${primaryCareerHost()}/r/${slug.toLowerCase()}`;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const result = await fetchCareerJob(slug.toLowerCase());
  if (!result.ok) {
    // Nieznany slug: strona 404 z `noindex` od Next.js zamiast metadanych
    // z `index` (layout od 20.10.2026 indeksuje strony kariery). Kod HTTP i tak
    // zostaje 200 — `app/loading.tsx` wysyła odpowiedź przed decyzją.
    if (result.notFound) notFound();
    return { title: "Rekrutacja" };
  }
  const { job, status } = result.data;
  const description =
    status === "closed"
      ? "Ta rekrutacja została zakończona."
      : job.subtitle || paramsSummary(job.params) || "Rekrutacja IT — B2Bnetwork";
  return {
    title: job.title,
    description,
    // Etap 6 (decyzja D3 Artura 20.10.2026): otwarte rekrutacje w Google,
    // zamknięta wypada z indeksu.
    robots:
      status === "open" ? { index: true, follow: true } : { index: false, follow: true },
    // Kilka linków jednej rekrutacji = jedna oferta w Google: canonical na link z tablicy.
    alternates: { canonical: canonicalUrl(result.data.canonical_slug ?? slug) },
    openGraph: { title: job.title, description, type: "website", locale: "pl_PL" },
    twitter: { card: "summary_large_image", title: job.title, description },
  };
}

export default async function CareerJobPage({ params }: PageProps) {
  const { slug } = await params;
  // Tablica (cache 60 s w API) daje krótkie nazwy umiejętności i podobne oferty;
  // jej awaria nie blokuje strony oferty.
  const [data, board, { base }] = await Promise.all([load(slug), fetchCareerBoard(), careerRequestContext()]);
  const posting = jobPostingJsonLd(data, canonicalUrl(data.canonical_slug ?? slug));
  return (
    <>
      {posting ? (
        <script
          type="application/ld+json"
          // Dane JobPosting dla Google — z opublikowanego opisu, `<` zamieniony.
          dangerouslySetInnerHTML={{ __html: jsonLdString(posting) }}
        />
      ) : null}
      <OfferPage data={data} board={board.ok ? board.data.jobs : null} base={base} />
    </>
  );
}
