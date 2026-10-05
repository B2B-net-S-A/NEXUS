/**
 * Strażnik „nic nie znika" dla przebudowy pełnego profilu kandydata
 * (wariant B, wersja 5, 04.10.2026).
 *
 * Spis (`lib/candidate-profile-feature-inventory.json`) to funkcje profilu
 * z przeglądu, każda z plikiem i markerem — napisem, który musi w tym pliku
 * istnieć. Przenosiny funkcji zmieniają `file`; wpis zostaje. Wpis znika
 * wyłącznie z `removed_reason`, czyli z zapisaną decyzją. Test czyta ŹRÓDŁA,
 * nie renderuje ekranu.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import inventory from "@/lib/candidate-profile-feature-inventory.json";

interface Feature {
  id: string;
  opis: string;
  file: string;
  marker: string;
  home: string;
  removed_reason?: string;
}

const SRC = resolve(__dirname, "..", "..");
const features = inventory.features as Feature[];

/** Tylu funkcji liczył spis w dniu założenia — lista może tylko rosnąć. */
const MIN_FEATURES = 84;

describe("spis funkcji profilu kandydata", () => {
  it("nie kurczy się po cichu", () => {
    expect(features.length).toBeGreaterThanOrEqual(MIN_FEATURES);
    expect(new Set(features.map((f) => f.id)).size).toBe(features.length);
  });

  it.each(features.map((f) => [f.id, f] as const))("%s żyje we wskazanym pliku", (_id, feature) => {
    if (feature.removed_reason) {
      expect(feature.removed_reason.length).toBeGreaterThan(20);
      return;
    }
    expect(feature.home.length).toBeGreaterThan(0);
    expect(readFileSync(resolve(SRC, feature.file), "utf8")).toContain(feature.marker);
  });
});
