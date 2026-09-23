import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CareerRecruiterView } from "@/components/career/CareerRecruiterView";
import { fetchCareerRecruiter } from "@/lib/career/server";

import { careerRequestContext } from "../../_context";

interface PageProps {
  params: Promise<{ slug: string }>;
}

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const result = await fetchCareerRecruiter(slug.toLowerCase());
  const name = result.ok ? result.data.recruiter.first_name : null;
  const title = name ? `${name} — rekrutacje IT` : "Rekrutacje IT";
  const description = "Szukasz kolejnego projektu IT? Zostaw CV raz — odezwę się z konkretem.";
  return {
    title,
    description,
    robots: { index: false, follow: false },
    openGraph: { title, description, type: "website", locale: "pl_PL" },
    twitter: { card: "summary_large_image", title, description },
  };
}

export default async function CareerRecruiterPage({ params }: PageProps) {
  const { slug } = await params;
  const result = await fetchCareerRecruiter(slug.toLowerCase());
  if (!result.ok) {
    if (result.notFound) notFound();
    throw new Error("Nie udało się wczytać strony rekrutera.");
  }
  const { base, host } = await careerRequestContext();
  return <CareerRecruiterView data={result.data} base={base} host={host} />;
}
