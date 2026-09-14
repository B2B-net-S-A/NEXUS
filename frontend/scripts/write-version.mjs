#!/usr/bin/env node
// DEP-03 (audyt Codexa, 14.09.2026): smoke test deployu sprawdzał frontend
// wyłącznie po HTTP 200, więc STARY kontener frontendu (np. build, który padł
// po cichu, albo Traefik wciąż wskazujący poprzedni obraz) przechodził na
// zielono, dopóki tylko odpowiadał. Backend ma `/api/health.version`; frontend
// nie miał niczego, co mówiłoby, z którego commitu jest zbudowany.
//
// Ten skrypt pisze `public/version.json` PRZED `next build` (patrz Dockerfile
// etapu `builder`), więc plik trafia do obrazu razem z resztą `public/`.
// SHA pochodzi z build arg `NEXT_PUBLIC_GIT_SHA` (docker-compose.yml podaje
// tam `${GIT_SHA}` z Coolify, czyli `$SOURCE_COMMIT` — to samo źródło, które
// zasila `version` w `/api/health`). Middleware nie dotyka ścieżek z kropką
// (`matcher` wyklucza `.*\..*`), więc plik jest czytelny bez logowania.
//
// Plik NIE jest w repo (gitignore) — commitowana zaślepka z "unknown"
// wyglądałaby jak wynik builda, w którym ten krok nie zaszedł.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * Buduje treść `version.json` z otoczenia builda.
 * Kolejność źródeł: NEXT_PUBLIC_GIT_SHA (build arg frontendu) → GIT_SHA
 * (nazwa backendowa/Coolify) → "unknown". Pusty string liczy się jak brak.
 *
 * @param {Record<string, string | undefined>} env
 * @param {Date} now
 * @returns {{ sha: string, builtAt: string }}
 */
export function buildVersionPayload(env, now = new Date()) {
  const raw = env.NEXT_PUBLIC_GIT_SHA?.trim() || env.GIT_SHA?.trim() || "";
  return {
    sha: raw || "unknown",
    builtAt: now.toISOString(),
  };
}

/**
 * Zapisuje `public/version.json` obok tego skryptu (frontend/public/).
 * @param {Record<string, string | undefined>} env
 * @param {string} [outFile]
 */
export function writeVersionFile(env = process.env, outFile) {
  const target =
    outFile ?? resolve(dirname(fileURLToPath(import.meta.url)), "..", "public", "version.json");
  mkdirSync(dirname(target), { recursive: true });
  const payload = buildVersionPayload(env);
  writeFileSync(target, `${JSON.stringify(payload, null, 2)}\n`);
  return { target, payload };
}

const invokedDirectly =
  process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (invokedDirectly) {
  const { target, payload } = writeVersionFile();
  console.log(`version.json → ${target} (sha=${payload.sha})`);
}
