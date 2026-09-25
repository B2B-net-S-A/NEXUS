import type { CandidateSearchRequest } from "@/lib/candidate-search-api";

/**
 * Stan zaawansowanej wyszukiwarki (`/candidates/search`) w URL + walidacja
 * przedziałów (UAT B28, B29).
 *
 * URL niesie JEDEN parametr `s` z JSON-em pól, które różnią się od bazowego
 * requestu (domyślne + prefill). Request ma ~30 pól, w tym listy obiektów
 * (`languages`) i listy list (`q_any_groups`) — płaskie parametry jak w
 * `url-filters.ts` wymagałyby osobnego kodeka dla każdego kształtu, a JSON
 * jest bezstratny i taki sam, jak zapis w „zapisanych wyszukiwaniach".
 * Dzięki temu Wstecz z profilu wraca na te same filtry i tę samą stronę.
 */
export const SEARCH_REQUEST_URL_PARAM = "s";

export const EXPERIENCE_RANGE_REVERSED_MSG =
  "Minimalna liczba lat doświadczenia nie może być większa niż maksymalna.";
export const RATE_RANGE_REVERSED_MSG =
  "Minimalna stawka nie może być większa niż maksymalna.";

function rangeReversed(
  low: number | null | undefined,
  high: number | null | undefined,
): boolean {
  return low != null && high != null && low > high;
}

/** Lustro walidatora backendu (`CandidateSearchRequest.ranges_are_ordered`). */
export function experienceRangeError(
  request: Pick<CandidateSearchRequest, "experience_years_min" | "experience_years_max">,
): string | null {
  return rangeReversed(request.experience_years_min, request.experience_years_max)
    ? EXPERIENCE_RANGE_REVERSED_MSG
    : null;
}

/**
 * Pierwszy błąd walidacji requestu albo `null`. Odwrócony przedział to
 * niemożliwe kryterium — backend odpowiada 422, a widok nie ma czego
 * pokazywać, więc nie wysyła zapytania.
 */
export function searchRequestValidationError(
  request: CandidateSearchRequest,
): string | null {
  const experience = experienceRangeError(request);
  if (experience) return experience;
  if (rangeReversed(request.rate_hourly_min, request.rate_hourly_max)) {
    return RATE_RANGE_REVERSED_MSG;
  }
  return null;
}

/**
 * Pola, które mogą trafić do URL-a. `exclude_in_job_id` celowo poza listą —
 * to kontekst rekrutacji, własność widoku, nie użytkownika.
 */
const URL_REQUEST_KEYS = [
  "q_all",
  "q_any",
  "q_any_groups",
  "q_none",
  "q",
  "competence_category_ids",
  // Pola legacy zostają czytane (stare `?s=`); widok przekłada je na kubełki
  // (`toSearchSemanticsV2`) i sam zapisuje już wyłącznie kubełki niżej.
  "skills_must",
  "skills_any",
  "skills_none",
  "skills_required",
  "skills_required_any_groups",
  "skills_preferred",
  "skills_excluded",
  "open_to",
  "text_mode",
  "experience_years_min",
  "experience_years_max",
  "languages",
  "location_cities",
  "location_countries",
  "status",
  "availability_status",
  "availability_date_before",
  "notice_period_max",
  "rate_hourly_min",
  "rate_hourly_max",
  "sources",
  "tags",
  "has_cv",
  "has_linkedin",
  "is_champion",
  "is_ambassador",
  "open_to_side_projects",
  "open_to_sales_support",
  "open_to_expert_consult",
  "cv_parsed_after",
  "exclude_blacklisted",
  "sort",
  "page",
  "page_size",
  "search_mode",
  // Zapis v3 (po migracji semantyki) niesie `semantics_version: 2` — musi
  // przeżyć Wstecz z profilu, inaczej ten sam zapis pokazałby inny zbiór.
  "semantics_version",
  "hide_unknown",
] as const satisfies readonly (keyof CandidateSearchRequest)[];

type UrlRequestKey = (typeof URL_REQUEST_KEYS)[number];

function sameValue(a: unknown, b: unknown): boolean {
  // `null` i `undefined` znaczą to samo („nie ustawiono"); listy i obiekty
  // porównywane strukturalnie.
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

/** Różnica request − base jako JSON; pusty string, gdy nic się nie różni. */
export function searchRequestFingerprint(
  request: CandidateSearchRequest,
  base: CandidateSearchRequest,
): string {
  const diff: Partial<Record<UrlRequestKey, unknown>> = {};
  for (const key of URL_REQUEST_KEYS) {
    const value = request[key];
    if (value === undefined || sameValue(value, base[key])) continue;
    diff[key] = value;
  }
  return Object.keys(diff).length ? JSON.stringify(diff) : "";
}

export function encodeSearchRequest(
  request: CandidateSearchRequest,
  base: CandidateSearchRequest,
): URLSearchParams {
  const params = new URLSearchParams();
  const fingerprint = searchRequestFingerprint(request, base);
  if (fingerprint) params.set(SEARCH_REQUEST_URL_PARAM, fingerprint);
  return params;
}

function clampInt(raw: unknown, min: number, max: number, fallback: number): number {
  const n = typeof raw === "number" ? raw : Number(raw);
  return Number.isInteger(n) && n >= min && n <= max ? n : fallback;
}

/**
 * Odtwarza request z parametru `s`. Nieczytelny albo nieznany kształt =
 * baza (nigdy wyjątek — URL bywa wklejony ręcznie). Klucze spoza listy są
 * pomijane, strona i rozmiar strony przycinane do zakresu backendu.
 */
function sameShape(value: unknown, reference: unknown): boolean {
  if (reference === null || reference === undefined) {
    // Pole bez wartości bazowej: przyjmujemy tylko prymitywy, nigdy obiekty.
    return value === null || ["string", "number", "boolean"].includes(typeof value);
  }
  if (Array.isArray(reference)) return Array.isArray(value);
  if (value === null) return true;
  return typeof value === typeof reference && !Array.isArray(value);
}

export function decodeSearchRequest(
  raw: string | null | undefined,
  base: CandidateSearchRequest,
): CandidateSearchRequest {
  const out: CandidateSearchRequest = { ...base };
  if (!raw) return out;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return out;
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return out;
  const source = parsed as Record<string, unknown>;
  const target = out as Record<string, unknown>;
  for (const key of URL_REQUEST_KEYS) {
    if (!(key in source)) continue;
    // `?s=` jest kanałem pisanym przez użytkownika (zakładka, ręcznie
    // zredagowany adres): pole o innym typie niż w bazie (np. tablica jako
    // tekst) zostaje przy wartości bazowej zamiast wjechać do stanu i wywalić
    // konsumenta oczekującego tablicy.
    if (!sameShape(source[key], base[key])) continue;
    target[key] = source[key];
  }
  out.page = clampInt(out.page, 1, Number.MAX_SAFE_INTEGER, 1);
  out.page_size = clampInt(out.page_size, 1, 200, base.page_size ?? 50);
  return out;
}

/** Pola, które działają od razu — nie czekają na „Szukaj”. */
const IMMEDIATE_REQUEST_KEYS = new Set(["page", "page_size", "sort"]);

/**
 * Ile zmian w szkicu czeka na „Szukaj” (25.09.2026): każdy element listy
 * (słowo, umiejętność, miasto) i każde pole proste liczy się osobno.
 */
export function searchRequestChangeCount(
  draft: CandidateSearchRequest,
  applied: CandidateSearchRequest,
): number {
  const a = applied as unknown as Record<string, unknown>;
  const d = draft as unknown as Record<string, unknown>;
  const keys = new Set([...Object.keys(a), ...Object.keys(d)]);
  let changes = 0;
  for (const key of keys) {
    if (IMMEDIATE_REQUEST_KEYS.has(key)) continue;
    const left = a[key];
    const right = d[key];
    if (Array.isArray(left) || Array.isArray(right)) {
      const pool = new Map<string, number>();
      for (const item of Array.isArray(left) ? left : []) {
        const k = JSON.stringify(item);
        pool.set(k, (pool.get(k) ?? 0) + 1);
      }
      for (const item of Array.isArray(right) ? right : []) {
        const k = JSON.stringify(item);
        const n = pool.get(k) ?? 0;
        if (n > 0) pool.set(k, n - 1);
        else changes += 1;
      }
      for (const n of pool.values()) changes += n;
      continue;
    }
    const empty = (v: unknown) => v === undefined || v === null || v === "";
    if (empty(left) && empty(right)) continue;
    if (!sameValue(left, right)) changes += 1;
  }
  return changes;
}
