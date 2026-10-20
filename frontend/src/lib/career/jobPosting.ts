/**
 * Dane JobPosting (schema.org) strony rekrutacji — oferty w wynikach „Praca”
 * w Google (etap 6 linków, decyzja D3 Artura 20.10.2026).
 *
 * Tylko z tego, co strona i tak pokazuje kandydatowi (opublikowana wersja
 * opisu z publicznego API): bez klienta, stawek i kodów. Zamknięta rekrutacja
 * nie dostaje danych — Google ma ją usunąć z wyników.
 */

import type { CareerJobResponse } from "./api";

export const HIRING_ORGANIZATION = {
  "@type": "Organization",
  name: "B2B Network",
  legalName: "B2B.NET S.A.",
  sameAs: "https://b2bnetwork.pl",
} as const;

function description(job: CareerJobResponse["job"]): string {
  const parts: string[] = [];
  if (job.subtitle) parts.push(job.subtitle);
  if (job.about) parts.push(job.about);
  if (job.must.length) {
    parts.push(`Wymagania: ${job.must.map((m) => m.name).join(", ")}.`);
  }
  if (job.nice.length) parts.push(`Mile widziane: ${job.nice.join(", ")}.`);
  return parts.join("\n\n") || job.title;
}

/** Obiekt JSON-LD albo `null`, gdy rekrutacja jest zamknięta albo brak daty publikacji. */
export function jobPostingJsonLd(
  data: CareerJobResponse,
  url: string,
): Record<string, unknown> | null {
  if (data.status !== "open" || !data.published_at) return null;
  const { job } = data;
  const params = job.params;
  const remote = params?.remote_policy === "remote";
  // Google wymaga miejsca pracy albo pracy zdalnej. Bez miasta i bez trybu
  // zdalnego (także przy ukrytych „parametrach”) nie zgadujemy — fałszywe
  // TELECOMMUTE to naruszenie zasad danych o ofertach (audyt 21.10.2026).
  if (!remote && !params?.city) return null;
  const posting: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    title: job.title,
    description: description(job),
    datePosted: data.published_at,
    // Każda rekrutacja to współpraca B2B (decyzja 25.09.2026).
    employmentType: "CONTRACTOR",
    hiringOrganization: HIRING_ORGANIZATION,
    directApply: true,
    url,
    // Jedna rekrutacja = jedna oferta w Google, choć ma kilka linków (każdy rekruter swój).
    identifier: {
      "@type": "PropertyValue",
      name: "B2B Network",
      value: data.canonical_slug ?? job.slug,
    },
  };
  if (params?.city && !remote) {
    posting.jobLocation = {
      "@type": "Place",
      address: {
        "@type": "PostalAddress",
        addressLocality: params.city,
        addressCountry: "PL",
      },
    };
  }
  if (remote) {
    posting.jobLocationType = "TELECOMMUTE";
    posting.applicantLocationRequirements = { "@type": "Country", name: "Polska" };
  }
  return posting;
}

/** JSON do `<script type="application/ld+json">` — `<` zamieniony, żeby tekst nie zamknął znacznika. */
export function jsonLdString(value: Record<string, unknown>): string {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}
