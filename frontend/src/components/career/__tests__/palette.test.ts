import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { OG_COLORS, type CareerColor } from "@/components/career/palette";

const css = readFileSync(join(__dirname, "..", "career.css"), "utf8");

function cssVar(name: CareerColor): string | undefined {
  return new RegExp(`--kr-${name}:\\s*(#[0-9a-fA-F]{6})\\s*;`).exec(css)?.[1];
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

describe("paleta strony kariery", () => {
  it("career.css ma te same kolory co grafika OG i podgląd posta", () => {
    for (const name of Object.keys(OG_COLORS) as CareerColor[]) {
      expect(cssVar(name)?.toUpperCase(), `--kr-${name}`).toBe(OG_COLORS[name]);
    }
  });

  it("czerwony tytułu ma ≥ 3:1 na czarnym (duży tekst), a akcent ≥ 4,5:1", () => {
    expect(contrast(OG_COLORS.title, OG_COLORS.bg)).toBeGreaterThanOrEqual(3);
    expect(contrast(OG_COLORS.red, OG_COLORS.bg)).toBeGreaterThanOrEqual(4.5);
    // Bordo zostaje tylko pod białym tekstem (przycisk wysyłki) i w ozdobnikach.
    expect(contrast(OG_COLORS.bordo, OG_COLORS.bg)).toBeLessThan(3);
    expect(contrast(OG_COLORS.white, OG_COLORS.bordo)).toBeGreaterThanOrEqual(4.5);
  });

  it("tytuł strony nie jest już w bordo", () => {
    expect(css).toMatch(/\.kr-title-b\s*\{\s*color:\s*var\(--kr-title\)/);
  });
});
