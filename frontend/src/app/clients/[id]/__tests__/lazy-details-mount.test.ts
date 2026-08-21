import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * Strażnik leniwego montowania zwiniętych sekcji profilu klienta.
 *
 * Regresja jest CICHA i niewidoczna w interfejsie: zwinięty <details> montuje
 * swoje dzieci, więc każde wejście na profil klienta odpala zapytania paneli,
 * których nikt nie rozwinął (raport hit-ratio, listowanie dokumentów, cennik,
 * wiedza o kliencie). Nic nie pęka — odpowiedzi są liczone, serializowane
 * i wyrzucane, a rachunek płaci produkcyjny Postgres razy liczba otwarć
 * profilu przez wszystkich DL-i i TAC-ów.
 *
 * Test czyta ŹRÓDŁO, bo LazyDetails nie może zostać wyeksportowany z pliku
 * `page.tsx` — Next.js waliduje zestaw eksportów modułu strony i każdy
 * dodatkowy nazwany eksport wywraca type-check builda.
 */

const PAGE = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "page.tsx",
);

const HEAVY_CHILDREN = [
  "CooperationStatsSection",
  "MaterialsTab",
  "RateCardsTab",
  "KnowledgeTab",
];

function readPage(): string {
  return fs.readFileSync(PAGE, "utf8");
}

/** Komentarze opisują ten mechanizm słowami „<details>", więc muszą zniknąć,
 *  zanim policzymy realne użycia w JSX. */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
}

function lazyDetailsBlocks(source: string): string[] {
  // Bloki od otwarcia <LazyDetails do domykającego </LazyDetails>. Nie ma tu
  // zagnieżdżeń, więc proste dopasowanie wystarczy.
  return source.match(/<LazyDetails[\s\S]*?<\/LazyDetails>/g) ?? [];
}

describe("profil klienta — zwinięte sekcje montują się leniwie", () => {
  it("nie renderuje surowego <details> w drzewie zakładek", () => {
    const source = stripComments(readPage());
    // Jedyne dozwolone wystąpienie to definicja samego LazyDetails.
    const occurrences = source.match(/<details\b/g) ?? [];
    expect(occurrences).toHaveLength(1);
  });

  it("LazyDetails montuje dziecko dopiero po pierwszym otwarciu", () => {
    const source = readPage();
    // Flaga podnoszona przez onToggle i bramkująca render dziecka — bez niej
    // wrapper jest kosmetyką, a zapytania lecą tak samo jak przed zmianą.
    expect(source).toContain("if (e.currentTarget.open) setMounted(true);");
    expect(source).toContain("{mounted ? children : null}");
  });

  it.each(HEAVY_CHILDREN)("%s siedzi wewnątrz LazyDetails", (child) => {
    const source = readPage();
    const usage = new RegExp(`<${child}\\s`);
    // Komponent musi być użyty i każde jego użycie musi być objęte wrapperem.
    expect(usage.test(source)).toBe(true);

    const blocks = lazyDetailsBlocks(source);
    const wrapped = blocks.filter((block) => usage.test(block)).length;
    const total = (source.match(new RegExp(`<${child}\\s`, "g")) ?? []).length;
    expect(wrapped).toBe(total);
  });
});
