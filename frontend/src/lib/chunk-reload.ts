/**
 * Jednorazowe przeładowanie strony po błędzie ładowania chunka JS.
 *
 * Każdy deploy podmienia pliki `/_next/static/chunks/*`. Karta otwarta przed
 * deployem przy nawigacji sięga po chunk starej wersji, którego już nie ma —
 * dostaje ChunkLoadError i widzi „Coś poszło nie tak” zamiast strony. Pełne
 * przeładowanie pobiera nowy build i problem znika (reaudyt 14.09.2026).
 *
 * Przeładowujemy CO NAJWYŻEJ RAZ na okno: jeśli chunk nie wczyta się także po
 * odświeżeniu (deploy wciąż trwa, sieć leży), pętla przeładowań byłaby gorsza
 * od komunikatu o błędzie.
 */

export const CHUNK_RELOAD_STORAGE_KEY = "nexus:chunk-reload-at";
/** Po tym czasie kolejny błąd chunka może znów przeładować stronę. */
export const CHUNK_RELOAD_WINDOW_MS = 60_000;

const CHUNK_ERROR_RE =
  /ChunkLoadError|Loading (?:CSS )?chunk [\w-]+ failed|Failed to fetch dynamically imported module|Importing a module script failed/i;

export function isChunkLoadError(error: unknown): boolean {
  if (!error) return false;
  if (typeof error === "string") return CHUNK_ERROR_RE.test(error);
  const candidate = error as { name?: unknown; message?: unknown };
  const text = `${String(candidate.name ?? "")} ${String(candidate.message ?? "")}`;
  return CHUNK_ERROR_RE.test(text);
}

interface ReloadDeps {
  storage?: Pick<Storage, "getItem" | "setItem"> | null;
  reload?: () => void;
  now?: () => number;
}

/** Zwraca `true`, jeśli zlecono przeładowanie. */
export function reloadOnceForChunkError(error: unknown, deps: ReloadDeps = {}): boolean {
  if (!isChunkLoadError(error)) return false;
  const now = (deps.now ?? Date.now)();
  let storage = deps.storage;
  if (storage === undefined) {
    try {
      storage = typeof window !== "undefined" ? window.sessionStorage : null;
    } catch {
      storage = null;
    }
  }
  try {
    const last = Number(storage?.getItem(CHUNK_RELOAD_STORAGE_KEY) ?? "0");
    if (Number.isFinite(last) && now - last < CHUNK_RELOAD_WINDOW_MS) return false;
    storage?.setItem(CHUNK_RELOAD_STORAGE_KEY, String(now));
  } catch {
    // Brak sessionStorage (tryb prywatny, zablokowane dane witryny): bez znacznika
    // nie da się zagwarantować „tylko raz”, więc nie przeładowujemy wcale.
    return false;
  }
  if (!storage) return false;
  (deps.reload ?? (() => window.location.reload()))();
  return true;
}
