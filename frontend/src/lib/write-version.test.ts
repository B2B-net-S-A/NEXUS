/**
 * DEP-03 (audyt Codexa, 14.09.2026): smoke test deployu porównuje
 * `public/version.json` frontendu z oczekiwanym SHA. Plik pisze
 * `scripts/write-version.mjs` przed `next build` (Dockerfile). Test pilnuje
 * kontraktu treści (`sha`, `builtAt`) i kolejności źródeł SHA — bez tego
 * frontend zbudowany bez build arga wyglądałby na „zgodny” z niczym.
 */
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { buildVersionPayload, writeVersionFile } from "../../scripts/write-version.mjs";

const SHA = "0123456789abcdef0123456789abcdef01234567";
const NOW = new Date("2026-09-14T10:00:00.000Z");

describe("buildVersionPayload", () => {
  it("bierze SHA z NEXT_PUBLIC_GIT_SHA (build arg frontendu)", () => {
    expect(buildVersionPayload({ NEXT_PUBLIC_GIT_SHA: SHA }, NOW)).toEqual({
      sha: SHA,
      builtAt: "2026-09-14T10:00:00.000Z",
    });
  });

  it("wraca do GIT_SHA, gdy build arg frontendu jest pusty", () => {
    expect(buildVersionPayload({ NEXT_PUBLIC_GIT_SHA: "  ", GIT_SHA: SHA }, NOW).sha).toBe(SHA);
  });

  it("bez żadnego źródła pisze 'unknown' — smoke test ma to odrzucić, nie zgadywać", () => {
    expect(buildVersionPayload({}, NOW).sha).toBe("unknown");
  });
});

describe("writeVersionFile", () => {
  const dirs: string[] = [];
  afterEach(() => {
    for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true });
  });

  it("zapisuje poprawny JSON pod wskazaną ścieżką (tworząc katalog)", () => {
    const dir = mkdtempSync(join(tmpdir(), "nexus-version-json-"));
    dirs.push(dir);
    const target = join(dir, "public", "version.json");

    const result = writeVersionFile({ NEXT_PUBLIC_GIT_SHA: SHA }, target);

    expect(result.target).toBe(target);
    const parsed = JSON.parse(readFileSync(target, "utf8")) as { sha: string; builtAt: string };
    expect(parsed.sha).toBe(SHA);
    expect(Number.isNaN(Date.parse(parsed.builtAt))).toBe(false);
  });
});
