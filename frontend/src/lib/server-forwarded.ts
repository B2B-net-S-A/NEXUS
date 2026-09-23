/**
 * Nagłówki klienta dla odczytów SSR z publicznych stron (audyt 22.09 r2,
 * FE-N01).
 *
 * Strony publiczne (kariera, `/apply`, podpis, karta Championa) czytają API
 * z serwera Next.js po sieci compose. Backend liczy limit zapytań po skrajnie
 * PRAWYM wpisie `X-Forwarded-For` (`app/core/rate_limit.py`), a bez tego
 * nagłówka — po adresie peera, czyli kontenera frontu: WSZYSCY odwiedzający
 * dzielili jeden kubełek 60/min, a 429 renderowało się jak „link nieważny”.
 * Przekazujemy więc adres klienta (skrajnie prawy wpis, dopisany przez nasz
 * Traefik — lewe może podrobić klient) i `User-Agent` (backend nie liczy
 * wejść botów podglądu linków).
 */

import { headers } from "next/headers";

type HeaderSource = { get(name: string): string | null };

/** Czysta funkcja — testowalna bez kontekstu żądania Next.js. */
export function pickForwardedHeaders(source: HeaderSource): Record<string, string> {
  const out: Record<string, string> = {};
  const forwarded = source.get("x-forwarded-for");
  const rightmost = forwarded
    ?.split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .pop();
  const clientIp = rightmost || source.get("x-real-ip")?.trim();
  if (clientIp) out["x-forwarded-for"] = clientIp;
  const userAgent = source.get("user-agent");
  if (userAgent) out["user-agent"] = userAgent;
  return out;
}

/** Nagłówki bieżącego żądania do przekazania w `fetch` po stronie serwera. */
export async function forwardedClientHeaders(): Promise<Record<string, string>> {
  try {
    return pickForwardedHeaders(await headers());
  } catch {
    // Poza kontekstem żądania (build, test) — nic do przekazania.
    return {};
  }
}
