import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * API przeniesiono na api.nexus.b2bnetwork.pl (05.11.2026), a CSP
 * (`lib/csp.ts`) wpuszcza w `connect-src` tylko adres z NEXT_PUBLIC_API_URL.
 * Stara domena w kodzie przeglądarki = zablokowane żądanie (NEXUS-FE-C3).
 */
const SRC = join(process.cwd(), "src");
const LEGACY_API_HOST = "https://api.nexus.dynaminds.pl";

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "__tests__" ? [] : sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

describe("stara domena API", () => {
  it("nie wraca do kodu frontu jako adres żądań", () => {
    const offenders = sourceFiles(SRC)
      .filter((path) => readFileSync(path, "utf8").includes(LEGACY_API_HOST))
      .map((path) => relative(SRC, path));
    expect(offenders).toEqual([]);
  });
});
