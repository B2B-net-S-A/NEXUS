import type { Metadata } from "next";
import { headers } from "next/headers";

import { CareerTheme } from "@/components/career/CareerTheme";
import { careerMetadataBase } from "@/lib/career/host";

/**
 * Strona kariery dla kandydatów (`kariera.dynaminds.pl`, w NEXUSIE `/kariera`).
 *
 * `noindex`: dzielimy się linkiem na LinkedInie, a zamknięte rekrutacje nie
 * mają wisieć w Google. `metadataBase` = pochodzenie ŻĄDANIA (nagłówki
 * `x-forwarded-proto`/`x-forwarded-host` od Traefika), żeby adres grafiki Open
 * Graph był absolutny i wskazywał host, pod którym strona naprawdę działa.
 * Statyczna wartość z env dawała na produkcji `http://localhost:3000/...`.
 */
export async function generateMetadata(): Promise<Metadata> {
  const metadataBase = careerMetadataBase(await headers());
  return {
    ...(metadataBase ? { metadataBase } : {}),
    title: { default: "Kariera — Dynaminds", template: "%s — Dynaminds" },
    description: "Rekrutacje IT prowadzone przez zespół Dynaminds (B2B.NET S.A.).",
    robots: { index: false, follow: false, googleBot: { index: false, follow: false } },
  };
}

export default function CareerLayout({ children }: { children: React.ReactNode }) {
  return <CareerTheme>{children}</CareerTheme>;
}
