/**
 * Publiczne API strony kariery — typy i odczyt po stronie serwera.
 *
 * Kontrakt: `/api/public/career/*` (bez logowania). Odpowiedź NIGDY nie niesie
 * nazwy klienta ani stawek — strona renderuje wyłącznie to, co tu przyjdzie.
 * Odczyt idzie z serwera (RSC) po `INTERNAL_API_URL` (sieć compose), a wysyłka
 * formularza z przeglądarki po `NEXT_PUBLIC_API_URL`.
 */

import { cache } from "react";

import { forwardedClientHeaders } from "@/lib/server-forwarded";

export type RemotePolicy = "remote" | "hybrid" | "onsite";
export type WorkMode = "any" | "remote" | "hybrid" | "onsite";

export interface CareerRecruiter {
  first_name: string;
  slug: string | null;
}

export interface CareerJobParams {
  city: string | null;
  remote_policy: RemotePolicy | null;
  onsite_days_per_week: number | null;
  seniority: string | null;
  contract: string | null;
  start: string | null;
  duration: string | null;
}

export interface CareerJob {
  slug: string;
  title: string;
  subtitle: string | null;
  about: string | null;
  must: { name: string; note: string | null }[];
  nice: string[];
  params: CareerJobParams | null;
  show: { must: boolean; nice: boolean; params: boolean; process: boolean } | null;
}

export interface CareerJobResponse {
  status: "open" | "closed";
  recruiter: CareerRecruiter;
  job: CareerJob;
}

export interface CareerRecruiterJob {
  slug: string;
  title: string;
  city: string | null;
  remote_policy: RemotePolicy | null;
}

export interface CareerRecruiterResponse {
  recruiter: { first_name: string; slug: string };
  jobs: CareerRecruiterJob[];
}

/** Adres API dla odczytu z serwera (RSC, grafiki OG). */
export function serverApiBase(): string {
  return (
    process.env.INTERNAL_API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    "http://localhost:8000"
  ).replace(/\/+$/, "");
}

/** Adres API dla wysyłki z przeglądarki. */
export function browserApiBase(): string {
  return (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");
}

export type FetchResult<T> =
  | { ok: true; data: T }
  | { ok: false; notFound: boolean };

async function getJson<T>(
  path: string,
  extraHeaders: Record<string, string> = {},
): Promise<FetchResult<T>> {
  try {
    const res = await fetch(`${serverApiBase()}${path}`, {
      cache: "no-store",
      // FE-N01: adres i UA klienta — limit zapytań per odwiedzający, boty
      // podglądu linków nie liczą się jako wejścia.
      headers: { ...(await forwardedClientHeaders()), ...extraHeaders },
    });
    if (res.status === 404) return { ok: false, notFound: true };
    if (!res.ok) return { ok: false, notFound: false };
    return { ok: true, data: (await res.json()) as T };
  } catch {
    return { ok: false, notFound: false };
  }
}

// `cache` = jeden odczyt na żądanie. `generateMetadata` i strona pytają o to
// samo, a każdy GET podbija licznik wejść linku (`visit_count`) — bez tego
// jedno wejście kandydata liczyłoby się podwójnie.
// `countVisit: false` — grafika OG nie jest wejściem kandydata (FE-N01).
const NO_VISIT = { "x-nexus-count-visit": "0" };

export const fetchCareerJob = cache(
  (slug: string, countVisit: boolean = true): Promise<FetchResult<CareerJobResponse>> =>
    getJson<CareerJobResponse>(
      `/api/public/career/r/${encodeURIComponent(slug)}`,
      countVisit ? {} : NO_VISIT,
    ),
);

export const fetchCareerRecruiter = cache(
  (slug: string, countVisit: boolean = true): Promise<FetchResult<CareerRecruiterResponse>> =>
    getJson<CareerRecruiterResponse>(
      `/api/public/career/p/${encodeURIComponent(slug)}`,
      countVisit ? {} : NO_VISIT,
    ),
);
