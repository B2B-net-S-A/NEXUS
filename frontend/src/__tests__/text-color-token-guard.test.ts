import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Strażnik: klasa koloru tekstu z rodziny tokenów (`text-destructive…`,
 * `text-success…`, `text-muted…` itd.) musi mieć token w `@theme`
 * (`globals.css`). Tailwind po cichu nie generuje klasy bez tokenu, więc
 * napis dziedziczy kolor rodzica i wygląda jak zwykły tekst.
 *
 * 16.11.2026: 13 miejsc z `text-destructive-text` (Księgowość, okno szablonu
 * faktury, „Kto zna NEXUS”) — komunikaty o problemach miały na stagingu
 * `rgb(44, 32, 60)` zamiast czerwieni. Token `--destructive-text` istnieje,
 * ale jako zmienna, a klasą czerwonego napisu jest `text-destructive`
 * (`docs/claude/ui/design-system-ui-zawsze-przy-pracy-nad-wygladem.md`).
 *
 * Rodziny bierzemy z samych tokenów (pierwszy człon nazwy), więc `text-sm`,
 * `text-left`, `text-[13px]` i paleta Tailwinda (`text-red-600`) strażnika nie
 * dotyczą — on łapie tylko literówki i nieistniejące warianty tokenów.
 */

const SRC = join(__dirname, "..");
const GLOBALS = join(SRC, "app", "globals.css");

function walk(dir: string, accept: (name: string) => boolean, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name === "__tests__" || name === "__mocks__" || name === "node_modules") continue;
      walk(path, accept, out);
    } else if (accept(name)) {
      out.push(path);
    }
  }
  return out;
}

/** Nazwy kolorów z `@theme`: `--color-<nazwa>` i `--text-color-<nazwa>`. */
function themeColorNames(css: string): Set<string> {
  const names = new Set<string>();
  for (const match of css.matchAll(/--(?:text-)?color-([a-z0-9-]+)\s*:/g)) names.add(match[1]);
  return names;
}

/** Klasy `text-*` zdefiniowane ręcznie w CSS (`.text-x {` albo `@utility text-x`). */
function customTextClasses(css: string): Set<string> {
  const names = new Set<string>();
  for (const match of css.matchAll(/(?:\.|@utility\s+)text-([a-z0-9-]+)/g)) names.add(match[1]);
  return names;
}

/**
 * Klasy `text-<rodzina>…` bez tokenu w jednym pliku. Wariant (`dark:`,
 * `hover:`), `!` i przezroczystość (`/70`) nie zmieniają nazwy tokenu.
 */
function offendersIn(source: string, tokens: Set<string>, custom: Set<string>): string[] {
  const families = new Set([...tokens].map((name) => name.split("-")[0]));
  const found = new Set<string>();
  for (const match of source.matchAll(/(?<![\w-])!?text-([a-z][a-z0-9-]*)(?:\/[\w.[\]]+)?(?![\w-])/g)) {
    const name = match[1];
    if (!families.has(name.split("-")[0])) continue;
    if (tokens.has(name) || custom.has(name)) continue;
    found.add(`text-${name}`);
  }
  return [...found];
}

describe("klasy koloru tekstu tylko z tokenów @theme", () => {
  const globals = readFileSync(GLOBALS, "utf8");
  const tokens = themeColorNames(globals);
  const custom = new Set(
    walk(SRC, (name) => name.endsWith(".css")).flatMap((path) => [...customTextClasses(readFileSync(path, "utf8"))]),
  );

  it("czyta tokeny z globals.css (w tym text-destructive)", () => {
    expect(tokens.has("destructive")).toBe(true);
    expect(tokens.has("muted-foreground")).toBe(true);
    expect(tokens.has("destructive-text")).toBe(false);
  });

  it("łapie klasę bez tokenu, przepuszcza tokeny, rozmiary i paletę Tailwinda", () => {
    const sample = [
      'className="text-destructive-text"',
      'cn("dark:text-success-text/80", "!text-warning-muted-foreground")',
      'className="text-sm text-[13px] text-left text-red-600 text-destructive/80 hover:text-primary"',
    ].join("\n");
    expect(offendersIn(sample, tokens, custom).sort()).toEqual(["text-destructive-text", "text-success-text"]);
  });

  it("w kodzie frontu nie ma klas koloru tekstu bez tokenu", () => {
    const offenders = walk(SRC, (name) => /\.(tsx?|jsx?)$/.test(name) && !/\.test\.[tj]sx?$/.test(name)).flatMap(
      (path) => offendersIn(readFileSync(path, "utf8"), tokens, custom).map((cls) => `${relative(SRC, path)}: ${cls}`),
    );
    expect(offenders).toEqual([]);
  });
});
