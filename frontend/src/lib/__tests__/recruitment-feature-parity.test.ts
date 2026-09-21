/**
 * Strażnik „nic nie znika" dla przebudowy widoku rekrutacji (wersja 3).
 *
 * Spis (`lib/recruitment-feature-inventory.json`) powstał PRZED usunięciem
 * czegokolwiek. Każda funkcja wskazuje plik i marker — napis albo nazwę
 * komponentu, która musi w tym pliku istnieć. Przenosiny funkcji zmieniają
 * `file`; wpis zostaje. Wpis znika wyłącznie z `removed_reason`, czyli z
 * zapisaną decyzją, a nie przy okazji refaktoru.
 *
 * Test czyta ŹRÓDŁA, nie renderuje ekranów: ma złapać funkcję, która
 * wypadła z kodu, zanim ktokolwiek zauważy jej brak na produkcji.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { resolveLegacyJobTab } from "@/lib/job-detail-routing";
import inventory from "@/lib/recruitment-feature-inventory.json";

interface Feature {
  id: string;
  area: string;
  opis: string;
  file: string;
  marker: string;
  v3_home: string;
  removed_reason?: string;
}

const SRC = resolve(__dirname, "..", "..");
const features = inventory.features as Feature[];

/** Tylu funkcji liczył spis w dniu założenia — lista może tylko rosnąć. */
const MIN_FEATURES = 60;

function source(file: string): string {
  return readFileSync(resolve(SRC, file), "utf8");
}

describe("spis funkcji widoku rekrutacji", () => {
  it("nie kurczy się po cichu", () => {
    expect(features.length).toBeGreaterThanOrEqual(MIN_FEATURES);
    expect(new Set(features.map((f) => f.id)).size).toBe(features.length);
  });

  it.each(features.map((f) => [f.id, f] as const))(
    "%s żyje we wskazanym pliku",
    (_id, feature) => {
      if (feature.removed_reason) {
        expect(feature.removed_reason.length).toBeGreaterThan(20);
        return;
      }
      expect(feature.v3_home.length).toBeGreaterThan(0);
      expect(source(feature.file)).toContain(feature.marker);
    },
  );
});

describe("stare adresy zakładek rekrutacji", () => {
  const page = source("app/jobs/[id]/page.tsx");

  // Linki z `?tab=` są zapisane w bazie powiadomień i w zakładkach
  // przeglądarek. Identyfikator, którego strona nie zna, po cichu otwiera
  // zakładkę domyślną — odbiorca ląduje gdzie indziej bez słowa wyjaśnienia.
  it.each([...inventory.old_tab_ids, ...inventory.old_tab_aliases])(
    "?tab=%s jest nadal rozpoznawane",
    (tab) => {
      // 1) Strona zna identyfikator (klucz albo alias w `page.tsx` — te same
      //    stałe czyta backendowy `test_client_tab_links.py`).
      const known =
        page.includes(`"${tab}"`) || new RegExp(`\\b${tab}:\\s*"`).test(page);
      expect(known).toBe(true);
      // 2) …i wie, DOKĄD on prowadzi: widok + segment / sekcja panelu / okno.
      const target = resolveLegacyJobTab(tab);
      expect(target, `resolveLegacyJobTab("${tab}")`).not.toBeNull();
      expect(["people", "board", "champion"]).toContain(target?.view);
    },
  );

  it("alias widoku na stronie zgadza się z celem w `resolveLegacyJobTab`", () => {
    // Dwie mapy (strona: alias → widok; biblioteka: alias → widok + reszta)
    // nie mogą się rozjechać — inaczej link otwiera okno na złym widoku.
    const block = page.slice(page.indexOf("const JOB_DETAIL_TAB_ALIASES"));
    const body = block.slice(block.indexOf("{", block.indexOf("=")), block.indexOf("};"));
    const pairs = [...body.matchAll(/^\s*"?([a-z][a-z-]*)"?\s*:\s*"([a-z]+)"/gm)];
    expect(pairs.length).toBeGreaterThanOrEqual(inventory.old_tab_aliases.length);
    for (const [, alias, view] of pairs) {
      expect(resolveLegacyJobTab(alias)?.view, alias).toBe(view);
    }
  });

  it("strona tłumaczy stare adresy tą samą funkcją", () => {
    expect(page).toContain("resolveLegacyJobTab");
    expect(page).toContain("rewriteLegacyJobParams");
  });
});
