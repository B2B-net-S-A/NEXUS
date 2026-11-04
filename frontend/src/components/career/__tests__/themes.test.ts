import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { OG_COLORS } from "@/components/career/palette";
import {
  CAREER_THEME_IDS,
  CAREER_THEMES,
  careerTheme,
  mixHex,
  ogColors,
  themeTokens,
} from "@/components/career/themes";

const css = readFileSync(join(__dirname, "..", "career.css"), "utf8");
const backendThemes = readFileSync(
  join(__dirname, "..", "..", "..", "..", "..", "backend", "app", "services", "career_theme.py"),
  "utf8",
);

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

describe("szablony graficzne strony kariery (0478)", () => {
  it("lista szablonów jest ta sama co w backendzie (career_theme.THEME_LABELS)", () => {
    const block = /THEME_LABELS[^{]*\{([\s\S]*?)\n\}/.exec(backendThemes)?.[1] ?? "";
    const ids = [...block.matchAll(/"([a-z0-9]+)":/g)].map((m) => m[1]);
    expect(ids).toEqual([...CAREER_THEME_IDS]);
  });

  it.each(CAREER_THEME_IDS)("%s: tekst czytelny (WCAG AA)", (id) => {
    const t = CAREER_THEMES[id];
    for (const [name, color] of [
      ["text", t.text],
      ["heading", t.heading],
      ["muted", t.muted],
      ["para", t.para],
      ["accent", t.accent],
    ] as const) {
      expect(contrast(color, t.bg), `${id}.${name}`).toBeGreaterThanOrEqual(4.5);
    }
    // Komentarz `// …` (`--kr-comment` = muted) stoi też w formularzu na `--kr-form-bg`.
    const formBg = themeTokens(id)["--kr-form-bg"];
    if (formBg) {
      expect(contrast(t.muted, formBg), `${id}.muted na form-bg`).toBeGreaterThanOrEqual(4.5);
    }
    // Druga linia tytułu to duży tekst — wystarczy 3:1.
    expect(contrast(t.title, t.bg), `${id}.title`).toBeGreaterThanOrEqual(3);
    expect(contrast(t.btnText, t.btn), `${id}.btnText`).toBeGreaterThanOrEqual(4.5);
  });

  it("trzy szablony w barwach B2B Network zamiast 12 scen (28.10.2026)", () => {
    expect([...CAREER_THEME_IDS]).toEqual(["grafit", "terminal", "jasny"]);
    for (const id of CAREER_THEME_IDS) {
      // Czerwień marki z brand booka w ozdobnikach każdego szablonu.
      expect(CAREER_THEMES[id].decor).toBe("#E73748");
    }
  });

  it("dawna scena, pusty i nieznany identyfikator dostają Grafit", () => {
    expect(themeTokens("plan")).toEqual(themeTokens("grafit"));
    expect(themeTokens(null)).toEqual(themeTokens("grafit"));
    expect(ogColors("nie-ma-takiego")).toEqual(ogColors("grafit"));
    expect(themeTokens("terminal")["--kr-bg"]).toBe(CAREER_THEMES.terminal.bg);
    expect(Object.keys(ogColors("jasny")).sort()).toEqual(Object.keys(OG_COLORS).sort());
  });

  it("szablon nadpisuje wyłącznie zmienne zadeklarowane w career.css", () => {
    const declared = new Set(
      [...css.matchAll(/^\s*(--kr-[a-z-]+):/gm)].map((m) => m[1]),
    );
    for (const id of CAREER_THEME_IDS) {
      for (const name of Object.keys(themeTokens(id))) {
        expect(declared.has(name), `${id}: ${name} nie ma w .kr-root`).toBe(true);
      }
    }
  });

  it("każdy kolor w career.css poza blokiem tokenów idzie przez zmienną", () => {
    const afterTokens = css.slice(css.indexOf("--kr-scheme"));
    const hexes = [...afterTokens.matchAll(/#[0-9a-fA-F]{6}\b/g)].map((m) => m[0].toLowerCase());
    // Dwie świadome wyjątki: tło dokumentu pod stroną (czerń i jasny szablon).
    expect(new Set(hexes)).toEqual(new Set(["#000000", "#f5f3ee"]));
  });

  it("nieznany szablon to Grafit", () => {
    expect(careerTheme("xyz")).toBe(CAREER_THEMES.grafit);
  });

  it("mixHex miesza kanały liniowo", () => {
    expect(mixHex("#000000", "#FFFFFF", 0.5)).toBe("#808080");
    expect(mixHex("#0A0A0A", "#0A0A0A", 0.3)).toBe("#0A0A0A");
  });
});
