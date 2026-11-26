/**
 * Strażnik (26.11.2026): każde pytanie listy kandydatów z tekstem `q` niesie
 * semantykę v2 — `CANDIDATE_LOOKUP_PARAMS` (szukanie osoby w trakcie pisania),
 * `semantics_version` albo `filtersToApiParams` (lista i jej pochodne).
 *
 * Bez tego `GET /api/candidates` idzie ścieżką v1 (zostaje dla alertów
 * zapisanych wyszukiwań), która dla dwóch znaków czyta CV, profil i notatki
 * całej bazy bez indeksu: na produkcji paleta ⌘K trwała 90 s i zajmowała
 * 3 z 8 vCPU serwera. Reguła: `docs/claude/kandydaci-wyszukiwanie/szukanie-osoby-w-trakcie-pisania.md`.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(process.cwd(), "src");

// Harnessy `/preview/*` i Poligon odpowiadają na zapytania z atrapy — nie pytają serwera.
const SKIP_DIRS = new Set(["__tests__", "preview", "poligon"]);

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return SKIP_DIRS.has(name) ? [] : walk(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

const CALL = /\.get(?:<[^>]*>)?\(\s*["'`]\/api\/candidates["'`]|candidatesApi\.list\(/g;
// Wywołanie z tekstem: parametr `q` w obiekcie zaraz za adresem.
const WITH_TEXT = /[{,\s]q\s*:/;
const V2 = /CANDIDATE_LOOKUP_PARAMS|semantics_version|filtersToApiParams/;

function textQueriesWithoutV2(): string[] {
  const offenders: string[] = [];
  for (const file of walk(SRC)) {
    const source = readFileSync(file, "utf8");
    for (const match of source.matchAll(CALL)) {
      const start = match.index ?? 0;
      const window = source.slice(start, start + 400);
      if (!WITH_TEXT.test(window) || V2.test(window)) continue;
      const line = source.slice(0, start).split("\n").length;
      offenders.push(`${relative(process.cwd(), file)}:${line}`);
    }
  }
  return offenders;
}

describe("pytania listy kandydatów z tekstem `q`", () => {
  it("niosą semantykę v2 (dwa znaki w v1 czytają całą bazę)", () => {
    expect(textQueriesWithoutV2()).toEqual([]);
  });
});
