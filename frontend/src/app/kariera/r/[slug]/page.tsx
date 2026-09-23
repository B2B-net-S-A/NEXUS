import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CareerJobView } from "@/components/career/CareerJobView";
import { fetchCareerJob } from "@/lib/career/server";
import { paramsSummary } from "@/lib/career/format";

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

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const result = await fetchCareerJob(slug.toLowerCase());
  if (!result.ok) return { title: "Rekrutacja" };
  const { job, status } = result.data;
  const description =
    status === "closed"
      ? "Ta rekrutacja została zakończona."
      : job.subtitle || paramsSummary(job.params) || "Rekrutacja IT — Dynaminds";
  return {
    title: job.title,
    description,
    robots: { index: false, follow: false },
    openGraph: { title: job.title, description, type: "website", locale: "pl_PL" },
    twitter: { card: "summary_large_image", title: job.title, description },
  };
}

export default async function CareerJobPage({ params }: PageProps) {
  const { slug } = await params;
  const data = await load(slug);
  const { base, host } = await careerRequestContext();
  return <CareerJobView data={data} base={base} host={host} />;
}
