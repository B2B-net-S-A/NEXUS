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

describe("kanban spraw: nic nie znika", () => {
  it.each(inventory.features.map((feature) => [feature.id, feature] as const))("%s", (_id, feature) => {
    const source = readFileSync(resolve(process.cwd(), feature.file), "utf8");
    expect(source, `${feature.label}: nie ma „${feature.marker}” w ${feature.file}`).toContain(feature.marker);
  });
});
