/**
 * UAT B52: formularz edycji kontraktu miał 24 `<label>` bez `htmlFor`, pola
 * bez `id`, a etapy harmonogramu stawek — powtarzalny placeholder „np. 215,60"
 * i nienazwane daty bez identyfikacji etapu. Drzewo dostępności pokazywało
 * nienazwane kontrolki.
 *
 * Test czyta ŹRÓDŁO strony: sam formularz siedzi za sesją, kilkunastoma
 * zapytaniami i trybem edycji, więc test renderujący padałby z powodów
 * niezwiązanych z etykietami.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = readFileSync(join(__dirname, "..", "page.tsx"), "utf8");

function labelTags(): string[] {
  return SRC.match(/<label\b[^>]*>/g) ?? [];
}

describe("formularz edycji kontraktu — etykiety dostępności", () => {
  it("każda etykieta jest powiązana z kontrolką (htmlFor) albo nazywa grupę (id)", () => {
    const tags = labelTags();
    expect(tags.length).toBeGreaterThanOrEqual(24);
    const orphans = tags.filter((t) => !/\bhtmlFor=/.test(t) && !/\bid=/.test(t));
    expect(orphans).toEqual([]);
  });

  it("każde htmlFor wskazuje istniejące id kontrolki", () => {
    const targets = [...SRC.matchAll(/htmlFor="([^"]+)"/g)].map((m) => m[1]);
    expect(targets.length).toBeGreaterThanOrEqual(22);
    for (const id of targets) {
      expect(SRC, `brak kontrolki id="${id}"`).toContain(`id="${id}"`);
    }
    expect(new Set(targets).size).toBe(targets.length);
  });

  it("każdy <select> w pliku ma dostępną nazwę (aria-label, aria-labelledby albo <label htmlFor>)", () => {
    // Retest 14.09: select „Generuj z szablonu…" nie miał żadnej nazwy —
    // pierwsza opcja nie jest etykietą kontrolki.
    const selects = SRC.match(/<select\b[^>]*>/g) ?? [];
    expect(selects.length).toBeGreaterThanOrEqual(9);
    const htmlForTargets = new Set([...SRC.matchAll(/htmlFor="([^"]+)"/g)].map((m) => m[1]));
    const unnamed = selects.filter((tag) => {
      if (/\baria-label(ledby)?=/.test(tag)) return false;
      const id = tag.match(/\bid="([^"]+)"/)?.[1];
      return !(id && htmlForTargets.has(id));
    });
    expect(unnamed).toEqual([]);
  });

  it("etykiety grupowe stawek nazywają pojedyncze pole przez aria-labelledby", () => {
    for (const slug of ["framework-rate", "rate-candidate"]) {
      expect(SRC).toContain(`id="contract-edit-${slug}-label"`);
      expect(SRC).toContain(`aria-labelledby="contract-edit-${slug}-label"`);
    }
  });

  it("każda kwota i data etapu ma nazwę z rodzajem stawki i numerem etapu", () => {
    const stageInputs = SRC.match(/aria-label=\{`Etap \$\{idx \+ 1\} stawki [^`]*: (kwota|obowiązuje od|obowiązuje do)`\}/g) ?? [];
    // 2 harmonogramy × (kwota, od, do)
    expect(stageInputs).toHaveLength(6);
    expect(stageInputs.some((s) => s.includes("z umowy ramowej"))).toBe(true);
    expect(stageInputs.some((s) => s.includes("stawki kandydata"))).toBe(true);
    const removeButtons = SRC.match(/aria-label=\{`Usuń etap \$\{idx \+ 1\} stawki [^`]*`\}/g) ?? [];
    expect(removeButtons).toHaveLength(2);
  });
});
