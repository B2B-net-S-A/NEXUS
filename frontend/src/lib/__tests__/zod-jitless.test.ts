/**
 * NEXUS-FE-18 (25.09.2026): zod 4 sprawdzał `Function("")` przy każdym
 * schemacie i CSP raportowało to do Sentry. Formularze importują zod
 * wyłącznie przez `@/lib/zod`, który wyłącza tę ścieżkę.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

import { z } from "@/lib/zod";

const SRC = join(__dirname, "..", "..");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      return name === "node_modules" || name === "__tests__" ? [] : sources(path);
    }
    return /\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

describe("zod bez ścieżki eval", () => {
  it("konfiguracja wyłącza JIT", () => {
    expect(z.config().jitless).toBe(true);
  });

  it("nikt nie importuje zod z pominięciem @/lib/zod", () => {
    const offenders = sources(SRC)
      .filter((path) => relative(SRC, path) !== join("lib", "zod.ts"))
      .filter((path) => /from ["']zod(\/[^"']*)?["']/.test(readFileSync(path, "utf8")))
      .map((path) => relative(SRC, path));
    expect(offenders).toEqual([]);
  });
});
