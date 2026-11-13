import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Czerwony tekst (`text-destructive`) ma własny token `--destructive-text`
 * (13.11.2026). W trybie ciemnym `--destructive` to ciemna czerwień tła
 * przycisku pod jasny napis; jako kolor tekstu dawała na karcie ok. 1,8:1
 * i „P0 · minęło …” na liście `/jobs` było prawie niewidoczne.
 *
 * Kontrakt: tryb jasny wygląda jak przedtem (tekst = `--destructive`), a w
 * każdym ciemnym wariancie czerwony tekst ma co najmniej 4,5:1 (WCAG AA) na
 * powierzchniach, na których stoi. Tło i ramka zostają na `--destructive`.
 */
const css = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf8").replace(
  /\/\*[\s\S]*?\*\//g,
  "",
);

function block(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  expect(start, `brak bloku ${selector}`).toBeGreaterThan(-1);
  const body = css.slice(start, css.indexOf("}", start));
  const decls: Record<string, string> = {};
  for (const [, name, value] of body.matchAll(/(--[\w-]+):\s*([^;]+);/g)) {
    decls[name] = value.trim();
  }
  return decls;
}

/** Bloki w kolejności kaskady (specyficzność, potem kolejność w pliku). */
const WORLDS: Record<string, string[]> = {
  jasny: [":root", 'html[data-soft="true"]'],
  "jasny płaski": [":root"],
  "jasny tryb gry": [":root", 'html[data-soft="true"]', 'html[data-kids="true"]'],
  ciemny: [":root", ".dark", 'html[data-soft="true"]', 'html.dark[data-soft="true"]'],
  "ciemny płaski": [":root", ".dark"],
  "ciemny tryb gry": [
    ":root",
    ".dark",
    'html[data-soft="true"]',
    'html[data-kids="true"]',
    'html.dark[data-soft="true"]',
    'html.dark[data-kids="true"]',
  ],
};

function tokens(world: string): Record<string, string> {
  return Object.assign({}, ...WORLDS[world].map(block));
}

function resolve(name: string, decls: Record<string, string>, depth = 0): string {
  const value = decls[name];
  expect(value, `brak ${name}`).toBeDefined();
  expect(depth).toBeLessThan(10);
  return value.replace(/var\((--[\w-]+)\)/g, (_, ref: string) => resolve(ref, decls, depth + 1));
}

function luminance(hsl: string): number {
  const [h, s, l] = hsl.replace(/%/g, "").split(/\s+/).map(Number);
  const a = (s / 100) * Math.min(l / 100, 1 - l / 100);
  const channel = (n: number) => {
    const k = (n + h / 30) % 12;
    const c = l / 100 - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(0) + 0.7152 * channel(8) + 0.0722 * channel(4);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** Kolor `text-destructive`: Tailwind 4 bierze `--text-color-*`, a bez niego `--color-*`. */
function textDestructive(t: Record<string, string>): string {
  const theme = block("@theme inline");
  const mapped = theme["--text-color-destructive"] ?? theme["--color-destructive"];
  const token = mapped?.match(/^hsl\(var\((--[\w-]+)\)\)$/)?.[1];
  expect(token, `nieoczekiwane mapowanie ${mapped}`).toBeDefined();
  return resolve(token as string, t);
}

describe("czerwony tekst — token --destructive-text", () => {
  it("liczy kontrast jak WCAG", () => {
    expect(contrast("0 0% 100%", "0 0% 0%")).toBeCloseTo(21, 5);
    expect(contrast("0 0% 46.3%", "0 0% 100%")).toBeCloseTo(4.54, 1);
  });

  it("text-destructive bierze --destructive-text, a tło i ramka zostają na --destructive", () => {
    const theme = block("@theme inline");
    expect(theme["--text-color-destructive"]).toBe("hsl(var(--destructive-text))");
    expect(theme["--color-destructive"]).toBe("hsl(var(--destructive))");
  });

  it.each(["jasny", "jasny płaski", "jasny tryb gry"])("%s: czerwony tekst bez zmian", (world) => {
    const t = tokens(world);
    expect(textDestructive(t)).toBe(resolve("--destructive", t));
  });

  it.each(["ciemny", "ciemny płaski", "ciemny tryb gry"])(
    "%s: czerwony tekst ma co najmniej 4,5:1 na każdej powierzchni",
    (world) => {
      const t = tokens(world);
      const text = textDestructive(t);
      for (const surface of [
        "--background",
        "--card",
        "--popover",
        "--muted",
        "--accent",
        "--destructive-muted",
      ]) {
        expect(
          contrast(text, resolve(surface, t)),
          `${world}: tekst ${text} na ${surface} ${resolve(surface, t)}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    },
  );
});
