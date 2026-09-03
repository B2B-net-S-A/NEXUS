import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Opcje priorytetu w formularzu rekrutacji muszą pokrywać się z enumem backendu.
 *
 * Formularz oferował „Krytyczny" jako `value="critical"`, a `JobPriority`
 * w backendzie zna wyłącznie `low | medium | high | urgent`. Każdy zapis z tą
 * opcją kończył się twardym 422 („Input should be 'low', 'medium', 'high' or
 * 'urgent'"), a użytkownik nie miał jak tego naprawić w formularzu — jedyne, co
 * mógł zrobić, to wybrać inny priorytet.
 *
 * Rozjazd był WEWNĄTRZ frontendu: `types/client-profile.ts` deklarowało
 * poprawną unię od zawsze, tylko komponent trzymał własną, drugą kopię listy.
 * Przeżył, bo nic go nie pilnowało.
 *
 * Test czyta ŹRÓDŁO zamiast renderować `AddJobModal` — modal wymaga
 * QueryClienta, routera i kilku zapytań, a chroniona własność jest statyczna:
 * dotyczy każdego przyszłego `<option>`, nie tego jednego renderu, który
 * akurat zmontujemy.
 */

const SRC = join(__dirname, "..", "..");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC, relativePath), "utf-8");
}

/** Wartości `<option>` z bloku `<FieldGroup label="Priorytet">`. */
function priorityOptionValues(): string[] {
  const source = readSource("components/AppShell.tsx");
  const start = source.indexOf('<FieldGroup label="Priorytet">');
  expect(start, "nie znaleziono pola Priorytet w AppShell.tsx").toBeGreaterThan(-1);

  const end = source.indexOf("</FieldGroup>", start);
  const block = source.slice(start, end);
  return [...block.matchAll(/<option value="([^"]*)"/g)].map((m) => m[1]);
}

/** Warianty unii `JobPriority` z types/client-profile.ts. */
function backendPriorityValues(): string[] {
  const source = readSource("types/client-profile.ts");
  const match = source.match(/export type JobPriority\s*=\s*([^;]+);/);
  expect(match, "nie znaleziono typu JobPriority").not.toBeNull();
  return [...match![1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
}

describe("formularz rekrutacji — kontrakt priorytetu", () => {
  it("oferuje dokładnie te wartości, które przyjmuje backend", () => {
    const offered = priorityOptionValues();
    const accepted = backendPriorityValues();

    expect(offered.length).toBeGreaterThan(0);
    expect([...offered].sort()).toEqual([...accepted].sort());
  });

  it("nie oferuje `critical` — backend zna tylko `urgent`", () => {
    // Kotwica na konkretny incydent, nie tylko na równość zbiorów. Gdyby ktoś
    // „naprawił" rozjazd, dopisując `critical` do unii po stronie frontendu,
    // test wyżej znów by przechodził, a 422 wróciłoby.
    expect(priorityOptionValues()).not.toContain("critical");
    expect(backendPriorityValues()).not.toContain("critical");
  });
});
