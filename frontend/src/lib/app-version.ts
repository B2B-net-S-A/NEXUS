/**
 * Wersja frontu w otwartej karcie a wersja na serwerze.
 *
 * Karta otwarta przed wdrożeniem (albo przywrócona przez przeglądarkę z jej
 * pamięci) działa na starych plikach JS bez końca: pliki `/_next/static/*`
 * mają ważność roku w przeglądarce i w Cloudflare, więc stara wersja nie
 * dostaje błędu ładowania i `lib/chunk-reload.ts` nigdy się nie włącza.
 * 12.10.2026 Delivery Leadzi tworzyli rekrutacje na ekranie sprzed weekendu,
 * choć nowy był na produkcji od dwóch dni — admin, który odświeżył stronę,
 * widział już nowy.
 *
 * Paczka zna swój SHA (`NEXT_PUBLIC_GIT_SHA` z builda), serwer podaje swój
 * w `/version.json` (`scripts/write-version.mjs`). Różnica = stara karta.
 * Czyste funkcje; kiedy pytać i co pokazać — `components/AppVersionGuard.tsx`.
 */

export const VERSION_RELOAD_STORAGE_KEY = "nexus:version-reload-for";

const SHA_RE = /^[0-9a-f]{40}$/i;

/** SHA builda wypalony w paczce; pusty poza obrazem z wdrożenia (lokalnie, testy). */
export const BUILD_SHA = (process.env.NEXT_PUBLIC_GIT_SHA ?? "").trim();

export function isBuildSha(value: unknown): value is string {
  return typeof value === "string" && SHA_RE.test(value);
}

/** Serwer ma inny build niż karta. Bez pewnego SHA po obu stronach — nigdy. */
export function isOtherBuild(buildSha: string, deployedSha: unknown): deployedSha is string {
  return (
    isBuildSha(buildSha) &&
    isBuildSha(deployedSha) &&
    buildSha.toLowerCase() !== deployedSha.toLowerCase()
  );
}

/** SHA wdrożonego frontu; `null` = nie wiadomo (awaria, wdrożenie w toku). */
export async function fetchDeployedSha(
  fetchImpl: typeof fetch = fetch,
  now: () => number = Date.now,
): Promise<string | null> {
  try {
    // Parametr i `no-store`: odpowiedź nie może przyjść z pamięci przeglądarki ani pośrednika.
    const response = await fetchImpl(`/version.json?t=${now()}`, { cache: "no-store" });
    if (!response.ok) return null;
    const data: unknown = await response.json();
    const sha = (data as { sha?: unknown } | null)?.sha;
    return typeof sha === "string" ? sha : null;
  } catch {
    return null;
  }
}

interface ReloadDeps {
  storage?: Pick<Storage, "getItem" | "setItem"> | null;
  reload?: () => void;
}

export function reloadNow(): void {
  window.location.reload();
}

/**
 * Przeładowuje kartę najwyżej raz na daną wersję serwera. Gdyby po
 * przeładowaniu karta nadal była stara (dokument z jakiejś pamięci),
 * kolejne przeładowania nic by nie dały — wtedy zostaje komunikat.
 * Zwraca `true`, jeśli zlecono przeładowanie.
 */
export function reloadOnceForVersion(deployedSha: string, deps: ReloadDeps = {}): boolean {
  let storage = deps.storage;
  if (storage === undefined) {
    try {
      storage = typeof window !== "undefined" ? window.sessionStorage : null;
    } catch {
      storage = null;
    }
  }
  if (!storage) return false;
  try {
    if (storage.getItem(VERSION_RELOAD_STORAGE_KEY) === deployedSha) return false;
    storage.setItem(VERSION_RELOAD_STORAGE_KEY, deployedSha);
  } catch {
    // Zablokowane dane witryny: bez znacznika nie da się zagwarantować „raz”.
    return false;
  }
  (deps.reload ?? reloadNow)();
  return true;
}
