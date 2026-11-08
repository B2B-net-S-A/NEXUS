import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Harnessy `/preview/*` są poza buildem produkcyjnym, ale dalej kosztują:
 * nocny E2E, typy i utrzymanie przy każdej zmianie komponentu. Audyt z 07.11.2026
 * doliczył się setek tysięcy znaków kodu, który ogląda tylko test.
 *
 * Kolejne wartości to limit po każdym obniżeniu, ostatnia obowiązuje. Dopisuj
 * tylko niższą: nowy harness wymaga usunięcia starego, a makiety powstają na
 * stagingu (`docs/claude/ui/makiety-na-stagingu.md`).
 */
const HARNESS_LIMIT_HISTORY = [119];

const FRONTEND_ROOT = path.resolve(__dirname, "../..");
const PREVIEW_ROOT = path.join(FRONTEND_ROOT, "src/app/preview");

function countHarnesses(dir: string): number {
  return readdirSync(dir).reduce((count, entry) => {
    const entryPath = path.join(dir, entry);
    if (statSync(entryPath).isDirectory()) return count + countHarnesses(entryPath);
    return entry === "page.tsx" ? count + 1 : count;
  }, 0);
}

describe("harnessy /preview/*", () => {
  it("limit może tylko maleć", () => {
    HARNESS_LIMIT_HISTORY.slice(1).forEach((limit, index) => {
      expect(limit).toBeLessThan(HARNESS_LIMIT_HISTORY[index]);
    });
  });

  it("nie ma ich więcej niż wynosi limit", () => {
    const limit = HARNESS_LIMIT_HISTORY[HARNESS_LIMIT_HISTORY.length - 1];
    const count = countHarnesses(PREVIEW_ROOT);
    expect(
      count,
      `Harnessów jest ${count}, limit to ${limit}. Usuń nieużywany harness albo pokaż zmianę na stagingu.`,
    ).toBeLessThanOrEqual(limit);
  });

  it("build produkcyjny ich nie zawiera, a stack E2E tak", () => {
    const dockerfile = readFileSync(path.join(FRONTEND_ROOT, "Dockerfile"), "utf-8");
    expect(dockerfile).toContain(
      'RUN if [ "$NEXT_PUBLIC_PREVIEW_PUBLIC" != "1" ]; then rm -rf src/app/preview; fi',
    );
    const compose = readFileSync(path.join(FRONTEND_ROOT, "../docker-compose.e2e.yml"), "utf-8");
    expect(compose).toContain('NEXT_PUBLIC_PREVIEW_PUBLIC: "1"');
  });
});
