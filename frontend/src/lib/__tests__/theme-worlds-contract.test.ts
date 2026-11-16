import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { WORLD_IDS } from "@/lib/worlds/world-ids";
import { DARK_WORLD_IDS, THEME_WORLDS } from "@/store/theme";

/**
 * Światy wyglądu (`docs/claude/ui/swiaty-wygladu.md`). Każdy świat z galerii
 * ma blok tokenów, kółko w menu i miniaturę; tekst ma kontrast co najmniej
 * 4,5:1 (WCAG AA); przyciski nie są czerwone, bo czerwień znaczy „pilne”.
 */
const css = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf8");
const layout = readFileSync(join(process.cwd(), "src/app/layout.tsx"), "utf8");

type Tokens = Record<string, string>;

function parse(body: string): Tokens {
  const out: Tokens = {};
  for (const m of body.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) out[m[1]] = m[2].trim();
  return out;
}

function firstBlock(selector: string): Tokens {
  const start = css.indexOf(`${selector} {`);
  expect(start, selector).toBeGreaterThan(-1);
  return parse(css.slice(start, css.indexOf("}", start)));
}

function worldTokens(id: string): Tokens {
  const out: Tokens = {};
  const re = new RegExp(`html\\[data-world="${id}"\\]\\s*\\{([^}]*)\\}`, "g");
  for (const m of css.matchAll(re)) Object.assign(out, parse(m[1]));
  return out;
}

const root = firstBlock("\n  :root");
const dark = { ...root, ...firstBlock("\n  .dark") };
const general = parse(css.match(/html\[data-world\]\s*\{([^}]*)\}/)?.[1] ?? "");

function resolve(tokens: Tokens, key: string, depth = 0): string {
  const value = tokens[key];
  const ref = value?.match(/^var\((--[a-z0-9-]+)\)$/);
  return ref && depth < 5 ? resolve(tokens, ref[1], depth + 1) : value;
}

function hslToRgb(value: string): [number, number, number] {
  const [h, s, l] = value.split(/\s+/).slice(0, 3).map((x) => parseFloat(x));
  const sat = s / 100;
  const light = l / 100;
  const k = (n: number) => (n + h / 30) % 12;
  const a = sat * Math.min(light, 1 - light);
  const f = (n: number) => light - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [f(0), f(8), f(4)];
}

function luminance(value: string): number {
  const ch = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const [r, g, b] = hslToRgb(value).map(ch);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const PAIRS: Array<[string, string]> = [
  ["--foreground", "--background"],
  ["--card-foreground", "--card"],
  ["--muted-foreground", "--card"],
  ["--primary-foreground", "--primary"],
  ["--sidebar-foreground", "--sidebar"],
  ["--world-nav-active", "--sidebar"],
];

describe("światy wyglądu — kontrakt", () => {
  it("lista światów zgadza się z listą zapisu na koncie", () => {
    expect([...WORLD_IDS].sort()).toEqual(["none", "game", ...THEME_WORLDS.map((w) => w.id)].sort());
  });

  it("skrypt startowy zna wszystkie ciemne światy (bez mignięcia jasnego tła)", () => {
    const list = layout.match(/t=\[([^\]]+)\]\.indexOf\(w\)/)?.[1] ?? "";
    expect(list.replace(/"/g, "").split(",").sort()).toEqual([...DARK_WORLD_IDS].sort());
  });

  for (const world of THEME_WORLDS) {
    describe(world.label, () => {
      const tokens = { ...(world.scheme === "dark" ? dark : root), ...general, ...worldTokens(world.id) };

      it("ma tokeny, kółko w menu i miniaturę w galerii", () => {
        expect(worldTokens(world.id)["--primary"], "--primary").toBeDefined();
        expect(css).toContain(`.world-swatch-${world.id} `);
        expect(css).toContain(`.world-thumb-${world.id} `);
      });

      it.each(PAIRS)("kontrast %s na %s co najmniej 4,5:1", (fg, bg) => {
        expect(contrast(resolve(tokens, fg), resolve(tokens, bg))).toBeGreaterThanOrEqual(4.5);
      });

      it("przyciski nie są czerwone (czerwień = pilne)", () => {
        const [h, s] = resolve(tokens, "--primary").split(/\s+/).map((x) => parseFloat(x));
        const reddish = (h <= 12 || h >= 348) && s >= 35;
        expect(reddish).toBe(false);
      });
    });
  }
});
