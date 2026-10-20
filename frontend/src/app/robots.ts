import type { MetadataRoute } from "next";
import { headers } from "next/headers";

import { careerHosts, isCareerHost, requestHost } from "@/lib/career/host";

/**
 * `robots.txt` zależny od hosta (etap 6 linków, decyzja D3 Artura 20.10.2026).
 *
 * Domena kariery: wszystko dozwolone — tablica, otwarte rekrutacje (z danymi
 * JobPosting) i strony rekruterów mają być w Google; zamknięte rekrutacje i 404
 * niosą `noindex` w samej stronie. `/kariera/*` też zostaje otwarte, bo tam
 * leżą grafiki Open Graph, a LinkedIn czyta ten plik.
 * Host aplikacji: nic do indeksowania (logowanie, dane wewnętrzne).
 * Middleware pomija ścieżki z kropką, więc jeden plik obsługuje oba hosty.
 */
export const dynamic = "force-dynamic";

export default async function robots(): Promise<MetadataRoute.Robots> {
  const onCareerHost = isCareerHost(requestHost(await headers()), careerHosts());
  return onCareerHost
    ? { rules: { userAgent: "*", allow: "/" } }
    : { rules: { userAgent: "*", disallow: "/" } };
}
