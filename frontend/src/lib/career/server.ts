/**
 * Odczyty strony kariery wykonywane WYŁĄCZNIE po stronie serwera (RSC, grafiki
 * OG). Osobny moduł, bo `forwardedClientHeaders` czyta `next/headers`, a
 * `lib/career/api.ts` importuje też komponent klienta (`CareerApplyForm`) —
 * wspólny moduł wywracał build frontendu (audyt 22.09 r2, FE-N01).
 */

import { cache } from "react";

import {
  serverApiBase,
  type CareerJobResponse,
  type CareerRecruiterResponse,
  type FetchResult,
} from "@/lib/career/api";
import { forwardedClientHeaders } from "@/lib/server-forwarded";

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
