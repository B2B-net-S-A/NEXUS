import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { RecruiterPage } from "@/components/career/site/RecruiterPage";
import { fetchCareerBoard, fetchCareerRecruiter } from "@/lib/career/server";

import { careerRequestContext } from "../../_context";

interface PageProps {
  params: Promise<{ slug: string }>;
}

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const result = await fetchCareerRecruiter(slug.toLowerCase());
  // Nieznany adres: 404 z `noindex` zamiast metadanych z `index` (jak `r/[slug]`).
  if (!result.ok && result.notFound) notFound();
  const name = result.ok ? result.data.recruiter.first_name : null;
  const title = name ? `${name} — rekrutacje IT` : "Rekrutacje IT";
  const description = "Szukasz kolejnego projektu IT? Zostaw CV raz — odezwę się z konkretem.";
  return {
    title,
    description,
    robots: { index: true, follow: true },
    openGraph: { title, description, type: "website", locale: "pl_PL" },
    twitter: { card: "summary_large_image", title, description },
  };
}

export default async function CareerRecruiterPage({ params }: PageProps) {
  const { slug } = await params;
  // Tablica (cache 60 s w API) daje kartom podtytuł i technologie; jej awaria nie blokuje strony.
  const [result, board, { base, host }] = await Promise.all([
    fetchCareerRecruiter(slug.toLowerCase()),
    fetchCareerBoard(),
    careerRequestContext(),
  ]);
  if (!result.ok) {
    if (result.notFound) notFound();
    throw new Error("Nie udało się wczytać strony rekrutera.");
  }
  return <RecruiterPage data={result.data} board={board.ok ? board.data.jobs : null} base={base} host={host} />;
}
