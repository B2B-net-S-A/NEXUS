/**
 * Strażnik „nic nie znika" dla przebudowy Kontraktów i Zamówień klienta
 * (wersja B: tabela z panelem szczegółów, 29.09.2026).
 *
 * Spis (`lib/orders-contracts-feature-inventory.json`) to 88 funkcji
 * z makiety, każda z plikiem i markerem — napisem, który musi w tym pliku
 * istnieć. Przenosiny funkcji zmieniają `file`; wpis zostaje. Wpis znika
 * wyłącznie z `removed_reason`, czyli z zapisaną decyzją, a nie przy okazji
 * refaktoru. Test czyta ŹRÓDŁA, nie renderuje ekranów.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import inventory from "@/lib/orders-contracts-feature-inventory.json";

interface Feature {
  id: string;
  opis: string;
  file: string;
  marker: string;
  b_home: string;
  removed_reason?: string;
}

const SRC = resolve(__dirname, "..", "..");
const features = inventory.features as Feature[];

/** Tylu funkcji liczył spis w dniu założenia — lista może tylko rosnąć. */
const MIN_FEATURES = 88;

describe("spis funkcji Kontraktów i Zamówień", () => {
  it("nie kurczy się po cichu", () => {
    expect(features.length).toBeGreaterThanOrEqual(MIN_FEATURES);
    expect(new Set(features.map((f) => f.id)).size).toBe(features.length);
  });

  it.each(features.map((f) => [f.id, f] as const))("%s żyje we wskazanym pliku", (_id, feature) => {
    if (feature.removed_reason) {
      expect(feature.removed_reason.length).toBeGreaterThan(20);
      return;
    }
    expect(feature.b_home.length).toBeGreaterThan(0);
    expect(readFileSync(resolve(SRC, feature.file), "utf8")).toContain(feature.marker);
  });
});
