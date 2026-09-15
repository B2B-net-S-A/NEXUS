import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * UAT B56: `html[data-soft="true"]` ustawia jasne `--background` i ma wyższą
 * specyficzność niż `.dark`. Ciemny blok stylu „Wyraźny” musi więc nadpisać tło
 * sam — inaczej ciemny tryb zostawia jasne płótno pod jasnym tekstem (≈1:1).
 */
describe("dark + soft theme contract", () => {
  const css = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf8");

  function block(selector: string): string {
    const start = css.indexOf(`${selector} {`);
    expect(start).toBeGreaterThan(-1);
    return css.slice(start, css.indexOf("}", start));
  }

  it("soft dark overrides the canvas with the dark background token", () => {
    const dark = block(".dark").match(/--background:\s*([^;]+);/)?.[1];
    const softDark = block('html.dark[data-soft="true"]').match(/--background:\s*([^;]+);/)?.[1];
    expect(softDark).toBeDefined();
    expect(softDark?.trim()).toBe(dark?.trim());
  });
});
