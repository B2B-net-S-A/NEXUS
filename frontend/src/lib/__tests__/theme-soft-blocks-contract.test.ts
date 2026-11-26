import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * „Klocki + ciemne menu” — wygląd bez motywu (decyzja Artura 26.11.2026,
 * `docs/claude/ui/wyrazny-bez-motywu-klocki-i-ciemne-menu.md`). Działa tylko
 * bez świata i bez Gry; granatowe menu ma czytelny tekst (WCAG AA 4,5:1).
 */
const css = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf8");
const topbar = readFileSync(join(process.cwd(), "src/components/v2/shell/TopbarV2.tsx"), "utf8");

const LIGHT = 'html[data-soft="true"]:not(.dark):not([data-kids="true"]):not([data-world])';

function tokens(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  expect(start, selector).toBeGreaterThan(-1);
  const out: Record<string, string> = {};
  for (const m of css.slice(start, css.indexOf("}", start)).matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) {
    out[m[1]] = m[2].trim();
  }
  return out;
}

function luminance(hsl: string): number {
  const [h, s, l] = hsl.split(/\s+/).map((x) => parseFloat(x));
  const a = (s / 100) * Math.min(l / 100, 1 - l / 100);
  const f = (n: number) => {
    const k = (n + h / 30) % 12;
    return l / 100 - a * Math.max(-1, Math.min(k - 3, Math.min(9 - k, 1)));
  };
  const ch = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * ch(f(0)) + 0.7152 * ch(f(8)) + 0.0722 * ch(f(4));
}

/** Dzieli listę selektorów po przecinkach poza nawiasami (`:is(a, b)` zostaje w całości). */
function topLevelSelectors(list: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let current = "";
  for (const ch of list) {
    if (ch === "(") depth += 1;
    if (ch === ")") depth -= 1;
    if (ch === "," && depth === 0) {
      out.push(current.trim());
      current = "";
    } else {
      current += ch;
    }
  }
  out.push(current.trim());
  return out.filter(Boolean);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

describe("wyraźny bez motywu: klocki i ciemne menu", () => {
  it("granatowe menu ma tekst i tekst pomocniczy co najmniej 4,5:1, także po najechaniu", () => {
    const t = tokens(LIGHT);
    for (const bg of [t["--sidebar"], t["--sidebar-accent"]]) {
      expect(contrast(t["--sidebar-foreground"], bg)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(t["--sidebar-muted"], bg)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("tokeny spodu klocków są w jasnym i ciemnym trybie", () => {
    expect(tokens(LIGHT)["--edge"]).toBeDefined();
    expect(
      tokens('html.dark[data-soft="true"]:not([data-kids="true"]):not([data-world])')["--edge"]
    ).toBeDefined();
  });

  it("każda reguła z --edge działa tylko bez świata i bez Gry", () => {
    const code = css.replace(/\/\*[\s\S]*?\*\//g, "");
    const rules = [...code.matchAll(/([^{}]+)\{([^{}]*var\(--edge(?:-soft)?\)[^{}]*)\}/g)];
    expect(rules.length).toBeGreaterThan(3);
    for (const [, selector] of rules) {
      for (const part of topLevelSelectors(selector)) {
        expect(part, part).toContain(':not([data-world])');
        expect(part, part).toContain(':not([data-kids="true"])');
      }
    }
  });

  it("górny pasek ma znacznik, na który celuje arkusz", () => {
    expect(topbar).toContain('data-app-topbar=""');
    expect(css).toContain("[data-app-topbar]");
  });
});
