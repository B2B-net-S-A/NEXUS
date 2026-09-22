import type { Metadata } from "next";

import { CareerTheme } from "@/components/career/CareerTheme";
import { careerHosts } from "@/lib/career/host";

const host = careerHosts()[0];

/**
 * Strona kariery dla kandydatów (`kariera.dynaminds.pl`, w NEXUSIE `/kariera`).
 *
 * `noindex`: dzielimy się linkiem na LinkedInie, a zamknięte rekrutacje nie
 * mają wisieć w Google. `metadataBase` = host kariery, żeby adres grafiki Open
 * Graph był absolutny i wskazywał domenę publiczną (LinkedIn nie pójdzie za
 * adresem względnym).
 */
export const metadata: Metadata = {
  ...(host ? { metadataBase: new URL(`https://${host}`) } : {}),
  title: { default: "Kariera — Dynaminds", template: "%s — Dynaminds" },
  description: "Rekrutacje IT prowadzone przez zespół Dynaminds (B2B.NET S.A.).",
  robots: { index: false, follow: false, googleBot: { index: false, follow: false } },
};

export default function CareerLayout({ children }: { children: React.ReactNode }) {
  return <CareerTheme>{children}</CareerTheme>;
}
