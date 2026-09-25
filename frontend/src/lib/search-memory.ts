/**
 * Pamięć wyszukiwania ręcznego w przeglądarce (decyzja 25.09.2026).
 *
 * - Ostatnie wyszukiwanie LISTY `/candidates` (sessionStorage, ta karta):
 *   zastosowane filtry jako query string, przewinięcie listy i ostatnio
 *   otwarta osoba — powrót z profilu albo menu nie zaczyna od zera.
 * - „Ostatnie wyszukiwania” (localStorage, per użytkownik): 10 pozycji listy
 *   i rekrutacji; z nich biorą się też „ostatnio używane słowa”.
 * - Ostatnie wyszukiwanie w „Szukaj ręcznie” rekrutacji (localStorage, per
 *   użytkownik i rekrutacja): 30 dni, najwyżej 50 rekrutacji.
 *
 * Pamięć jest wygodą, nie źródłem prawdy: każdy odczyt i zapis jest w
 * try/catch, a strona działa tak samo bez niej. Wylogowanie czyści prefiks
 * (`lib/session.ts`).
 */

export const SEARCH_MEMORY_PREFIX = "nexus:search-memory:";
const LIST_KEY = `${SEARCH_MEMORY_PREFIX}list`;
export const RECENT_LIMIT = 10;
export const JOB_MEMORY_LIMIT = 50;
export const JOB_MEMORY_TTL_MS = 30 * 24 * 60 * 60 * 1000;

function session(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

function local(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

function readJson(store: Storage | null, key: string): unknown {
  if (!store) return null;
  try {
    const raw = store.getItem(key);
    return raw ? (JSON.parse(raw) as unknown) : null;
  } catch {
    return null;
  }
}

function writeJson(store: Storage | null, key: string, value: unknown): void {
  if (!store) return;
  try {
    store.setItem(key, JSON.stringify(value));
  } catch {
    /* pełna albo zablokowana pamięć — wyszukiwanie działa bez niej */
  }
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

// ── Ostatnie wyszukiwanie listy ────────────────────────────────────────────

export interface ListSearchMemory {
  /** Zastosowane filtry listy (`encodeFilters`), bez `?`. */
  query: string;
  scrollTop: number;
  lastOpenedId: number | null;
  savedAt: number;
}

export function readListSearch(): ListSearchMemory | null {
  const v = readJson(session(), LIST_KEY);
  if (!isRecord(v) || typeof v.query !== "string") return null;
  return {
    query: v.query,
    scrollTop: typeof v.scrollTop === "number" && v.scrollTop > 0 ? v.scrollTop : 0,
    lastOpenedId: typeof v.lastOpenedId === "number" ? v.lastOpenedId : null,
    savedAt: typeof v.savedAt === "number" ? v.savedAt : 0,
  };
}

export function writeListSearch(patch: Partial<Omit<ListSearchMemory, "savedAt">>): void {
  const current = readListSearch() ?? { query: "", scrollTop: 0, lastOpenedId: null, savedAt: 0 };
  const next: ListSearchMemory = { ...current, ...patch, savedAt: Date.now() };
  // Nowe filtry = nowa lista: stare przewinięcie i wyróżnienie nic nie znaczą.
  if (patch.query !== undefined && patch.query !== current.query) {
    next.scrollTop = patch.scrollTop ?? 0;
    next.lastOpenedId = patch.lastOpenedId ?? null;
  }
  writeJson(session(), LIST_KEY, next);
}

export function clearListSearch(): void {
  try {
    session()?.removeItem(LIST_KEY);
  } catch {
    /* brak pamięci */
  }
}

// ── „Ostatnie wyszukiwania” ────────────────────────────────────────────────

export interface RecentSearch {
  kind: "list" | "job";
  jobId: number | null;
  /** Krótki opis do menu („Java + Kafka · bez junior”). */
  label: string;
  /** Lista: query string filtrów; rekrutacja: JSON zastosowanego requestu. */
  query: string;
  keywords: string[];
  at: number;
  total: number | null;
}

function recentKey(userId: number | string | null | undefined): string | null {
  return userId == null ? null : `${SEARCH_MEMORY_PREFIX}recent:${userId}`;
}

function parseRecent(v: unknown): RecentSearch | null {
  if (!isRecord(v)) return null;
  if ((v.kind !== "list" && v.kind !== "job") || typeof v.query !== "string") return null;
  return {
    kind: v.kind,
    jobId: typeof v.jobId === "number" ? v.jobId : null,
    label: typeof v.label === "string" ? v.label : "",
    query: v.query,
    keywords: Array.isArray(v.keywords)
      ? v.keywords.filter((k): k is string => typeof k === "string")
      : [],
    at: typeof v.at === "number" ? v.at : 0,
    total: typeof v.total === "number" ? v.total : null,
  };
}

export function readRecentSearches(userId: number | string | null | undefined): RecentSearch[] {
  const key = recentKey(userId);
  if (!key) return [];
  const v = readJson(local(), key);
  if (!Array.isArray(v)) return [];
  return v.map(parseRecent).filter((r): r is RecentSearch => r !== null).slice(0, RECENT_LIMIT);
}

export function pushRecentSearch(
  userId: number | string | null | undefined,
  entry: Omit<RecentSearch, "at"> & { at?: number },
): RecentSearch[] {
  const key = recentKey(userId);
  if (!key) return [];
  const fresh: RecentSearch = { ...entry, at: entry.at ?? Date.now() };
  const rest = readRecentSearches(userId).filter(
    (r) => !(r.kind === fresh.kind && r.jobId === fresh.jobId && r.query === fresh.query),
  );
  const next = [fresh, ...rest].slice(0, RECENT_LIMIT);
  writeJson(local(), key, next);
  return next;
}

/** Słowa kluczowe z ostatnich wyszukiwań, bez powtórzeń (najnowsze pierwsze). */
export function recentKeywords(
  userId: number | string | null | undefined,
  limit = 8,
): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const r of readRecentSearches(userId)) {
    for (const k of r.keywords) {
      const norm = k.trim().toLowerCase();
      if (!norm || seen.has(norm)) continue;
      seen.add(norm);
      out.push(k.trim());
      if (out.length >= limit) return out;
    }
  }
  return out;
}

// ── Ostatnie wyszukiwanie w rekrutacji ─────────────────────────────────────

export interface JobSearchMemory {
  request: Record<string, unknown>;
  at: number;
}

function jobKey(userId: number | string | null | undefined): string | null {
  return userId == null ? null : `${SEARCH_MEMORY_PREFIX}job:${userId}`;
}

function readJobMap(
  userId: number | string | null | undefined,
  now = Date.now(),
): Record<string, JobSearchMemory> {
  const key = jobKey(userId);
  if (!key) return {};
  const v = readJson(local(), key);
  if (!isRecord(v)) return {};
  const out: Record<string, JobSearchMemory> = {};
  for (const [id, entry] of Object.entries(v)) {
    if (!isRecord(entry) || !isRecord(entry.request) || typeof entry.at !== "number") continue;
    if (now - entry.at > JOB_MEMORY_TTL_MS) continue;
    out[id] = { request: entry.request, at: entry.at };
  }
  return out;
}

export function readJobSearch(
  userId: number | string | null | undefined,
  jobId: number,
  now = Date.now(),
): JobSearchMemory | null {
  return readJobMap(userId, now)[String(jobId)] ?? null;
}

export function writeJobSearch(
  userId: number | string | null | undefined,
  jobId: number,
  request: Record<string, unknown>,
  now = Date.now(),
): void {
  const key = jobKey(userId);
  if (!key) return;
  const map = readJobMap(userId, now);
  map[String(jobId)] = { request, at: now };
  const kept = Object.entries(map)
    .sort((a, b) => b[1].at - a[1].at)
    .slice(0, JOB_MEMORY_LIMIT);
  writeJson(local(), key, Object.fromEntries(kept));
}

export function clearJobSearch(userId: number | string | null | undefined, jobId: number): void {
  const key = jobKey(userId);
  if (!key) return;
  const map = readJobMap(userId);
  delete map[String(jobId)];
  writeJson(local(), key, map);
}

/** Wylogowanie: pamięć wyszukiwań nie może doczekać na kolejną osobę. */
export function clearSearchMemory(): void {
  for (const store of [session(), local()]) {
    if (!store) continue;
    try {
      for (let i = store.length - 1; i >= 0; i -= 1) {
        const key = store.key(i);
        if (key?.startsWith(SEARCH_MEMORY_PREFIX)) store.removeItem(key);
      }
    } catch {
      /* brak pamięci */
    }
  }
}
