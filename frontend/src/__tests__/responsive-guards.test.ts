import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Strażniki responsywności (audyt 23.09.2026, docs/responsiveness-audit-2026-09-23).
 * Każdy pilnuje reguły, której złamanie psuło WSZYSTKIE ekrany naraz albo
 * ukrywało akcje na urządzeniach dotykowych, a jsdom tego nie widzi.
 */

const SRC = join(__dirname, "..");

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name === "__tests__" || name === "node_modules") continue;
      sourceFiles(path, out);
    } else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) {
      out.push(path);
    }
  }
  return out;
}

describe("responsywność — reguły wspólne", () => {
  it("shell nie używa h-screen/100vh (dół strony chował się pod paskiem przeglądarki mobilnej)", () => {
    // Komentarze w shellu tłumaczą, czemu NIE h-screen — liczy się tylko kod.
    const shell = readFileSync(join(SRC, "components/v2/shell/AppShellV2.tsx"), "utf8")
      .split("\n")
      .filter((line) => !/^\s*(\/\/|\*|\/\*)/.test(line))
      .join("\n");
    expect(shell).not.toMatch(/\bh-screen\b|100vh/);
    expect(shell).toMatch(/\bh-dvh\b/);
  });

  it("pola formularzy mają 16 px na dotyku (iOS nie przybliża strony przy fokusie)", () => {
    const css = readFileSync(join(SRC, "app/globals.css"), "utf8");
    const block = css.match(/@media \(pointer: coarse\) \{[\s\S]*?font-size: max\(16px, 1em\)/);
    expect(block, "brak reguły 16 px dla pól na urządzeniach dotykowych").not.toBeNull();
  });

  it("akcje po najechaniu są widoczne na dotyku (hover nie istnieje na telefonie)", () => {
    // Goły `opacity-0 … group-hover:opacity-100` chowa przycisk na zawsze na
    // ekranie dotykowym — w Tailwind v4 `hover:` działa tylko przy myszy.
    const bare = /(^|[\s"'`])opacity-0(?=[\s"'`])[^"'`\n]*group-hover:opacity-100/;
    const offenders = sourceFiles(SRC)
      .filter((file) => !relative(SRC, file).startsWith("app/preview/"))
      .flatMap((file) =>
        readFileSync(file, "utf8")
          .split("\n")
          .map((line, index) => ({ line, index }))
          .filter(({ line }) => bare.test(line))
          .map(({ index }) => `${relative(SRC, file)}:${index + 1}`),
      );
    expect(
      offenders,
      "użyj `pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 focus-within:opacity-100`",
    ).toEqual([]);
  });
});
