import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Strażnik: `page.tsx` i `layout.tsx` w `src/app` eksportują tylko pola, które
 * Next.js dopuszcza w pliku trasy. Dodatkowy eksport wartości (funkcja
 * pomocnicza, stała klucza zapytania) wywraca `tsc` na typach, które Next
 * generuje w `.next/types` (`checkFields<Diff<…>>`). Pomocnik idzie do
 * `src/lib/` albo do komponentu. Eksport samego typu nie przeszkadza —
 * znika przy kompilacji.
 */

const APP = join(__dirname, "..", "app");

const ALLOWED = new Set([
  "default",
  "config",
  "generateStaticParams",
  "revalidate",
  "dynamic",
  "dynamicParams",
  "fetchCache",
  "preferredRegion",
  "runtime",
  "maxDuration",
  "metadata",
  "generateMetadata",
  "viewport",
  "generateViewport",
  "experimental_ppr",
]);

function routeFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name === "__tests__" || name === "node_modules") continue;
      routeFiles(path, out);
    } else if (/^(page|layout)\.(tsx|ts|jsx|js)$/.test(name)) {
      out.push(path);
    }
  }
  return out;
}

/** Nazwy eksportowanych WARTOŚCI (bez `export type` / `export interface`). */
function valueExports(source: string): string[] {
  const names: string[] = [];
  const declaration =
    /^export\s+(?:declare\s+)?(?:async\s+)?(?:function\*?|const|let|var|class|enum)\s+([A-Za-z_$][\w$]*)/gm;
  for (const match of source.matchAll(declaration)) names.push(match[1]);
  for (const match of source.matchAll(/^export\s*\{([^}]*)\}/gm)) {
    for (const spec of match[1].split(",")) {
      const item = spec.trim();
      if (!item || item.startsWith("type ")) continue;
      names.push(item.split(/\s+as\s+/).pop()!.trim());
    }
  }
  return names;
}

function forbiddenExports(source: string): string[] {
  return valueExports(source).filter((name) => !ALLOWED.has(name));
}

describe("eksporty plików tras Next.js", () => {
  it("rozpoznaje eksporty wartości i pomija typy", () => {
    expect(forbiddenExports("export function hitRatioTone() {}")).toEqual(["hitRatioTone"]);
    expect(forbiddenExports('export const QUERY_KEY = ["x"] as const;')).toEqual(["QUERY_KEY"]);
    expect(forbiddenExports("export { helper, type Row };")).toEqual(["helper"]);
    expect(forbiddenExports("export { helper as default };")).toEqual([]);
    expect(forbiddenExports("export type Row = { id: number };")).toEqual([]);
    expect(forbiddenExports("export type { Overview };")).toEqual([]);
    expect(forbiddenExports("export interface Props { id: number }")).toEqual([]);
    expect(forbiddenExports("export default function Page() {}")).toEqual([]);
    expect(forbiddenExports('export const dynamic = "force-dynamic";')).toEqual([]);
    expect(forbiddenExports("export async function generateMetadata() {}")).toEqual([]);
  });

  it("page.tsx i layout.tsx nie eksportują nic poza polami Next.js", () => {
    const offenders = routeFiles(APP).flatMap((path) =>
      forbiddenExports(readFileSync(path, "utf8")).map(
        (name) => `${relative(APP, path)}: ${name}`,
      ),
    );
    expect(offenders).toEqual([]);
  });
});
