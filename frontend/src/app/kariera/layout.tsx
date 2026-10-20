import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";

import { CareerTheme } from "@/components/career/CareerTheme";
import { careerMetadataBase } from "@/lib/career/host";

/**
 * Strona kariery dla kandydatów (`kariera.b2bnetwork.pl`, w NEXUSIE `/kariera`).
 *
 * Indeksowanie: od 20.10.2026 (etap 6, decyzja D3 Artura) strony kariery są
 * w Google — tablica, otwarte rekrutacje z danymi JobPosting, strony
 * rekruterów. Zamknięta rekrutacja sama ustawia `noindex` (`r/[slug]`),
 * a 404 dostaje go od Next.js. `metadataBase` = pochodzenie ŻĄDANIA (nagłówki
 * `x-forwarded-proto`/`x-forwarded-host` od Traefika), żeby adres grafiki Open
 * Graph był absolutny i wskazywał host, pod którym strona naprawdę działa.
 * Statyczna wartość z env dawała na produkcji `http://localhost:3000/...`.
 */
export async function generateMetadata(): Promise<Metadata> {
  const metadataBase = careerMetadataBase(await headers());
  return {
    ...(metadataBase ? { metadataBase } : {}),
    title: { default: "Kariera — B2B Network", template: "%s — B2B Network" },
    description: "Rekrutacje IT prowadzone przez zespół B2B Network (B2B.NET S.A.).",
    robots: { index: true, follow: true },
  };
}

/** Pasek przeglądarki i przewijanie poza stronę w kolorze strony (czerń). */
export const viewport: Viewport = {
  themeColor: "#000000",
  colorScheme: "dark",
};

export default function CareerLayout({ children }: { children: React.ReactNode }) {
  return <CareerTheme page>{children}</CareerTheme>;
}
