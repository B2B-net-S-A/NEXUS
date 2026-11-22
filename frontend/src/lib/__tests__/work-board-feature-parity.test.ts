/**
 * Strażnik „nic nie znika” dla kanbanu spraw (warunek Artura z 22.10.2026).
 *
 * Każda funkcja wskazuje plik i marker, który musi w nim istnieć. Przenosiny
 * zmieniają `file`; wpis znika tylko z `removed_reason`. Test czyta źródła.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import inventory from "@/lib/work-board-feature-inventory.json";

interface Feature {
  id: string;
  label: string;
  file: string;
  marker: string;
  removed_reason?: string;
}

const features = inventory.features as Feature[];

/** Tylu funkcji liczył spis 20.11.2026 (zdjęcie „Tablicy Opieki”) — lista może tylko rosnąć. */
const MIN_FEATURES = 15;

describe("kanban spraw: nic nie znika", () => {
  it("spis nie kurczy się po cichu", () => {
    expect(features.length).toBeGreaterThanOrEqual(MIN_FEATURES);
    expect(new Set(features.map((feature) => feature.id)).size).toBe(features.length);
  });

  it.each(features.map((feature) => [feature.id, feature] as const))("%s", (_id, feature) => {
    if (feature.removed_reason) {
      expect(feature.removed_reason.length).toBeGreaterThan(20);
      return;
    }
    const source = readFileSync(resolve(process.cwd(), feature.file), "utf8");
    expect(source, `${feature.label}: nie ma „${feature.marker}” w ${feature.file}`).toContain(feature.marker);
  });
});
