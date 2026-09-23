import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// jsdom nie liczy układu, więc test czyta klasy ze źródła. Zachowanie
// sprawdzono w przeglądarce: bez `relative` element `sr-only` z karty
// zamówienia (nagłówek „Aktywna obsada” przy jednym konsultancie) liczył się
// względem całego dokumentu i wydłużał go do swojej pozycji w treści —
// `document.scrollingElement.scrollHeight` 2496 px przy shellu na 100% okna,
// z `relative` 0 (zgłoszenie 09.2026: puste tło pod kartą, urwany sidebar).
const source = readFileSync(
  path.resolve(__dirname, "../AppShellV2.tsx"),
  "utf8",
);

function classesOf(marker: string): string[] {
  const line = source.split("\n").find((l) => l.includes(marker));
  expect(line, `brak elementu z „${marker}” w AppShellV2`).toBeDefined();
  const match = line!.match(/className="([^"]+)"/);
  expect(match, `brak className przy „${marker}”`).not.toBeNull();
  return match![1].split(/\s+/);
}

describe("AppShellV2 — przewija się tylko <main>, nigdy dokument", () => {
  it("root shella jest pozycjonowany, ucina przepełnienie i ma wysokość okna", () => {
    const root = classesOf("app-shell-root");
    expect(root).toContain("relative");
    expect(root).toContain("overflow-hidden");
    // `h-dvh`: na telefonie 100vh (`h-screen`) jest wyższe niż widoczny obszar.
    expect(root).toContain("h-dvh");
    expect(root).not.toContain("h-screen");
  });

  it("<main> jest pozycjonowany, więc elementy absolute zostają w jego przewijaniu", () => {
    const main = classesOf('id="main"');
    expect(main).toContain("relative");
    expect(main).toContain("overflow-y-auto");
  });
});
